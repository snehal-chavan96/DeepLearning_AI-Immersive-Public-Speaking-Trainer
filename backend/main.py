import uuid
import secrets
import os
import shutil
import tempfile
import traceback
import subprocess
from datetime import datetime, timedelta, timezone
from pydub import AudioSegment

from fastapi import FastAPI, Depends, HTTPException, Request, status, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import User, SessionHistory, PasswordResetToken, Recording, Analysis
from schemas import (
    RegisterRequest,
    LoginRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserResponse,
    TokenResponse,
    MessageResponse,
    SessionResponse,
    AnalysisResponse,
    SimplifiedAnalysisResponse,
    SimpleMetrics,
    SimpleEmotionResponse,
    SimpleCoachingFeedback,
    HistoryItem,
    DashboardStats,
)
from services.ai import (
    transcription_service,
    emotion_service,
    metric_service,
    scoring_service,
    feedback_service,
)
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
    get_current_user,
    security,
)
from fastapi.security import HTTPAuthorizationCredentials

# ── App Setup ────────────────────────────────────────────────

app = FastAPI(
    title="AI Public Speaking - Auth API",
    description="Secure authentication backend for the AI Public Speaking Training app",
    version="1.0.0",
)

# CORS — allow the React frontend to communicate
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Create all database tables on startup
Base.metadata.create_all(bind=engine)


# ── Health Check ─────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    """Health check endpoint to verify backend connectivity."""
    return {"status": "ok"}


# ── Register ─────────────────────────────────────────────────

@app.post("/signup", response_model=TokenResponse, tags=["Auth"])
def signup(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account and return an access token."""
    print(f"DEBUG: Signup attempt for email: {payload.email}")
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )

    # Create new user
    new_user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(new_user)
    db.flush() # Get user.id

    # Create a session
    token, jti = create_access_token(data={"sub": new_user.id})
    session = SessionHistory(
        user_id=new_user.id,
        token_jti=jti,
        is_active=True,
    )
    db.add(session)
    db.commit()
    db.refresh(new_user)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(new_user)
    )


# ── Login ────────────────────────────────────────────────────

@app.post("/login", response_model=TokenResponse, tags=["Auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a user and return an access token."""
    print(f"DEBUG: Login attempt for email: {payload.email}")
    
    user = db.query(User).filter(User.email == payload.email).first()
    
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated",
        )

    # Create a new session
    token, jti = create_access_token(data={"sub": user.id})
    session = SessionHistory(
        user_id=user.id,
        token_jti=jti,
        is_active=True,
    )
    db.add(session)
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


# ── Logout ───────────────────────────────────────────────────

@app.post("/logout", response_model=MessageResponse, tags=["Auth"])
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Invalidate the current session (token)."""

    payload = decode_token(credentials.credentials)
    jti = payload.get("jti")

    session = db.query(SessionHistory).filter(SessionHistory.token_jti == jti).first()
    if session:
        session.is_active = False
        session.expired_at = datetime.now(timezone.utc)
        db.commit()

    return MessageResponse(message="Successfully logged out")


# ── Forgot Password ─────────────────────────────────────────

@app.post("/forgot-password", response_model=MessageResponse, tags=["Auth"])
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Generate a password reset token. In production, this would email the user."""

    user = db.query(User).filter(User.email == payload.email).first()

    # Always return success to prevent email enumeration
    if not user:
        return MessageResponse(
            message="If an account with that email exists, a reset link has been sent.",
        )

    # Invalidate any previous reset tokens
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.is_used == False,
    ).update({"is_used": True})

    # Create a new reset token (valid for 1 hour)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset_token)
    db.commit()

    # In production: send email with reset link containing reset_token.token
    # For dev, we log it
    print(f"[DEV] Password reset token for {user.email}: {reset_token.token}")

    return MessageResponse(
        message="If an account with that email exists, a reset link has been sent.",
        detail=f"[DEV ONLY] Reset token: {reset_token.token}",
    )


# ── Reset Password ──────────────────────────────────────────

@app.post("/reset-password", response_model=MessageResponse, tags=["Auth"])
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a user's password using a valid reset token."""

    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == payload.token,
        PasswordResetToken.is_used == False,
    ).first()

    if not reset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    if reset.expires_at < datetime.now(timezone.utc):
        reset.is_used = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )

    # Update password
    user = db.query(User).filter(User.id == reset.user_id).first()
    user.hashed_password = hash_password(payload.new_password)
    user.updated_at = datetime.now(timezone.utc)

    # Mark token as used
    reset.is_used = True

    # Invalidate all active sessions (force re-login)
    db.query(SessionHistory).filter(
        SessionHistory.user_id == user.id,
        SessionHistory.is_active == True,
    ).update({"is_active": False, "expired_at": datetime.now(timezone.utc)})

    db.commit()

    return MessageResponse(message="Password has been successfully reset. Please log in with your new password.")


# ── Protected: Get Current User ──────────────────────────────

@app.get("/me", response_model=UserResponse, tags=["User"])
def get_me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(user)


# ── Protected: Session History ───────────────────────────────

@app.get("/sessions", response_model=list[SessionResponse], tags=["User"])
def get_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the current user's login session history."""
    request_id = str(uuid.uuid4())[:8]
    print(f"\n========== GET /sessions START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    
    try:
        print(f"[{request_id}] 💾 Querying sessions for user {user.id}")
        sessions = (
            db.query(SessionHistory)
            .filter(SessionHistory.user_id == user.id)
            .order_by(SessionHistory.created_at.desc())
            .limit(20)
            .all()
        )
        print(f"[{request_id}] ✅ Retrieved {len(sessions)} sessions from DB")
        result = [SessionResponse.model_validate(s) for s in sessions]
        print(f"[{request_id}] ✅ SUCCESS: Processed {len(result)} session records")
        return result
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /sessions: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"========== GET /sessions END [{request_id}] ==========\n")


@app.get("/stats", response_model=DashboardStats, tags=["User"])
def get_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return aggregate statistics for the user's performance."""
    request_id = str(uuid.uuid4())[:8]
    print(f"\n========== GET /stats START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    
    try:
        print(f"[{request_id}] 💾 Querying analyses for user {user.id}")
        print(f"[{request_id}] 📥 Filter: Recording.user_id == {user.id}")
        analyses = (
            db.query(Analysis)
            .join(Recording)
            .filter(Recording.user_id == user.id)
            .all()
        )
        print(f"[{request_id}] ✅ Retrieved {len(analyses)} analysis records from DB")
        
        if not analyses:
            print(f"[{request_id}] ⚠ No analyses found for user {user.id}, returning defaults")
            return DashboardStats(avg_confidence=0, total_speeches=0, total_hours=0, improvement=0)
        
        total_speeches = len(analyses)
        # Safe NULL handling: filter None values before averaging
        valid_scores = [a.confidence_score for a in analyses if a.confidence_score is not None]
        avg_confidence = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        
        print(f"[{request_id}] 📊 Confidence scores: {len(valid_scores)} valid out of {len(analyses)}")
        
        valid_durations = [a.recording.duration for a in analyses if a.recording.duration is not None]
        total_duration = sum(valid_durations) / 3600 if valid_durations else 0.0  # hours
        
        print(f"[{request_id}] 📊 Durations: {len(valid_durations)} valid out of {len(analyses)}")
        
        # Mock improvement for now, but in reality we'd compare first vs last session
        improvement = 15.0 if total_speeches > 1 else 0.0
        
        print(f"[{request_id}] 📊 Stats computed: avg_confidence={round(avg_confidence, 1)}, total_speeches={total_speeches}, total_hours={round(total_duration, 1)}, improvement={improvement}")
        print(f"[{request_id}] ✅ SUCCESS")
        
        return DashboardStats(
            avg_confidence=round(avg_confidence, 1),
            total_speeches=total_speeches,
            total_hours=round(total_duration, 1),
            improvement=improvement
        )
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /stats: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"========== GET /stats END [{request_id}] ==========\n")


@app.get("/history", response_model=list[HistoryItem], tags=["AI Coach"])
def get_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return a summary list of all past practice sessions."""
    request_id = str(uuid.uuid4())[:8]
    print(f"\n========== GET /history START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    
    try:
        # DEBUG (correct variable)
        total_records = db.query(Analysis).count()
        print(f"[{request_id}] 📊 TOTAL ANALYSIS RECORDS IN DB: {total_records}")
        
        print(f"[{request_id}] 💾 Querying analysis history for user {user.id}")
        print(f"[{request_id}] 📥 Filter: Recording.user_id == {user.id}")
        print(f"[{request_id}] 📥 Order: Analysis.created_at DESC")
        
        results = (
            db.query(Analysis)
            .join(Recording)
            .filter(Recording.user_id == user.id)
            .order_by(Analysis.created_at.desc())
            .all()
        )
        print(f"[{request_id}] ✅ Retrieved {len(results)} history records from DB")
        
        history = []
        for idx, a in enumerate(results):
            # Safe NULL handling: duration and score can be nullable in DB
            duration = a.recording.duration if a.recording.duration is not None else 0.0
            score = a.confidence_score if a.confidence_score is not None else 0.0
            
            item = HistoryItem(
                id=a.id,
                date=a.created_at,
                title=f"Session {a.created_at.strftime('%b %d')}",
                score=score,
                duration=round(duration, 2),
                emotion=a.emotion if a.emotion is not None else "Unknown"
            )
            history.append(item)
        
        print(f"[{request_id}] ✅ Processed {len(history)} history items")
        print(f"[{request_id}] ✅ SUCCESS")
        return history
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /history: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"========== GET /history END [{request_id}] ==========\n")


@app.get("/analysis/{analysis_id}", response_model=SimplifiedAnalysisResponse, tags=["AI Coach"])
def get_analysis_detail(
    analysis_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve full details for a specific past session."""
    request_id = str(uuid.uuid4())[:8]
    print(f"\n========== GET /analysis/{{analysis_id}} START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    print(f"📥 Input: analysis_id={analysis_id}")
    
    try:
        print(f"[{request_id}] 💾 Querying analysis {analysis_id} for user {user.id}")
        print(f"[{request_id}] 📥 Filter: Analysis.id == {analysis_id} AND Recording.user_id == {user.id}")
        
        analysis = (
            db.query(Analysis)
            .join(Recording)
            .filter(Analysis.id == analysis_id, Recording.user_id == user.id)
            .first()
        )
        
        if not analysis:
            print(f"[{request_id}] ⚠ Analysis {analysis_id} not found for user {user.id}")
            raise HTTPException(status_code=404, detail="Analysis not found")

        print(f"[{request_id}] ✅ Analysis record retrieved successfully")
        
        print(f"[{request_id}] 💡 Generating feedback from metrics...")
        # We need to reconstruct the feedback as it's not saved in the DB fully (only metrics)
        # Ideally, we'd save feedback too, but for now we regenerate or just return metrics
        feedback_result = feedback_service.generate_feedback(
            speech_rate=analysis.speech_rate,
            filler_words=analysis.filler_words,
            confidence_score=analysis.confidence_score,
            emotion=analysis.emotion
        )
        print(f"[{request_id}] ✅ Feedback generated")

        # Safe NULL handling for GET /analysis/{id} endpoint
        duration = analysis.recording.duration if analysis.recording.duration is not None else 0.0
        confidence_score = analysis.confidence_score if analysis.confidence_score is not None else 0.0
        
        print(f"[{request_id}] 📊 Response data: duration={duration}, confidence_score={confidence_score}, emotion={analysis.emotion}")
        print(f"[{request_id}] ✅ SUCCESS")
        
        return SimplifiedAnalysisResponse(
            id=analysis.id,
            transcription=analysis.transcription if analysis.transcription else "No speech detected",
            duration=duration,
            confidence_score=confidence_score,
            emotion=SimpleEmotionResponse(
                label=analysis.emotion if analysis.emotion else "Unknown",
                confidence=0.8
            ),
            metrics=SimpleMetrics(
                word_count=analysis.word_count if analysis.word_count is not None else 0,
                speech_rate=analysis.speech_rate if analysis.speech_rate is not None else 0.0,
                filler_words=analysis.filler_words if analysis.filler_words is not None else 0
            ),
            feedback=SimpleCoachingFeedback(**feedback_result),
            created_at=analysis.created_at
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /analysis/{{analysis_id}}: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"========== GET /analysis/{{analysis_id}} END [{request_id}] ==========\n")


# ── AI Practice & Analysis ───────────────────────────────────
# Helper: Convert WebM to WAV for Whisper/librosa compatibility
def convert_webm_to_wav(webm_path: str, wav_path: str) -> bool:
    """
    Convert WebM audio file to WAV format using ffmpeg.
    Returns True on success, False on failure.
    """
    try:
        # Use ffmpeg to convert WebM → WAV (16kHz mono for Whisper)
        cmd = [
            "ffmpeg",
            "-i", webm_path,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",  # Overwrite output file
            wav_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0:
            print(f"✓ Converted {webm_path} → {wav_path}")
            return True
        else:
            print(f"✗ ffmpeg conversion failed: {result.stderr.decode()}")
            return False
    except Exception as e:
        print(f"✗ Error converting WebM to WAV: {e}")
        return False


# Helper: Get audio duration safely
def get_audio_duration(audio_path: str) -> float:
    """
    Get audio duration in seconds using ffprobe.
    Falls back to 0.0 on error.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode == 0:
            duration = float(result.stdout.decode().strip())
            print(f"✓ Duration: {duration:.2f}s")
            return duration
        return 0.0
    except Exception as e:
        print(f"⚠ Could not get duration: {e}, using 0.0")
        return 0.0

@app.post("/analyze", response_model=SimplifiedAnalysisResponse, tags=["AI Coach"])
async def analyze_audio(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmp_path = None
    wav_path = None

    request_id = str(uuid.uuid4())[:8]
    print(f"\n========== ANALYZE START [{request_id}] ==========")
    print(f"👤 User ID: {user.id}")
    print(f"📄 File: {file.filename}")

    try:
        # 1. Save file
        ext = os.path.splitext(file.filename or "")[1].lower() or ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            tmp_file.write(await file.read())
            tmp_path = tmp_file.name

        print(f"[{request_id}] 📁 Saved temp file: {tmp_path}")

        # 2. Convert audio
        try:
            if ext in [".webm", ".mp4", ".m4a", ".ogg"]:
                wav_path = tmp_path.replace(ext, ".wav")
                print(f"[{request_id}] 🔄 Converting {ext} → WAV")

                audio = AudioSegment.from_file(tmp_path)
                audio.export(wav_path, format="wav")
            else:
                wav_path = tmp_path
                print(f"[{request_id}] ✅ Using original format")

        except Exception as e:
            print(f"[{request_id}] ❌ Audio conversion failed: {e}")
            raise HTTPException(status_code=400, detail="Audio conversion failed")

        print(f"[{request_id}] 🎧 WAV ready: {wav_path}")

        # 3. Duration
        duration = get_audio_duration(wav_path)
        print(f"[{request_id}] ⏱ Duration: {duration}")

        if duration <= 0:
            raise HTTPException(status_code=400, detail="Invalid audio duration")

        # 4. Whisper transcription
        print(f"[{request_id}] 🎤 Whisper starting...")

        try:
            transcription_result = transcription_service.transcribe(wav_path)

            print(f"[{request_id}] 🧾 RAW Whisper output: {transcription_result}")

            if not transcription_result or "text" not in transcription_result:
                raise ValueError("Invalid Whisper output")

        except Exception as e:
            print(f"[{request_id}] ❌ Whisper failed: {e}")
            raise HTTPException(status_code=500, detail="Transcription failed")

        text = transcription_result["text"]
        print(f"[{request_id}] 📝 Text preview: {text[:80]}")

        # 5. Metrics
        print(f"[{request_id}] 📊 Extracting metrics...")

        raw_metrics = metric_service.extract_metrics(
            transcription_result.get("segments", []),
            duration
        )

        print(f"[{request_id}] 📊 Metrics: {raw_metrics}")

        # 6. Score
        confidence_score = scoring_service.calculate_score(raw_metrics, duration) or 0.0
        print(f"[{request_id}] 🎯 Score: {confidence_score}")

        # 7. Emotion
        print(f"[{request_id}] 😊 Emotion detection...")

        try:
            emotion_raw = emotion_service.detect_emotion(wav_path)
            label = emotion_raw.get("prediction", "Neutral")

            emotion_result = {
                "label": "Nervous" if label in ["Fearful", "Angry"] else label,
                "confidence": emotion_raw.get("confidence", 0.7)
            }

        except Exception as e:
            print(f"[{request_id}] ⚠ Emotion fallback: {e}")
            emotion_result = {"label": "Neutral", "confidence": 0.7}

        print(f"[{request_id}] 😊 Emotion: {emotion_result}")

        # 8. Feedback
        print(f"[{request_id}] 💡 Generating feedback...")

        try:
            feedback_result = feedback_service.generate_feedback(
                speech_rate=raw_metrics.get("wpm", 0),
                filler_words=raw_metrics.get("filler_words", {}).get("total", 0),
                confidence_score=confidence_score,
                emotion=emotion_result["label"]
            )
        except Exception as e:
            print(f"[{request_id}] ⚠ Feedback fallback: {e}")
            feedback_result = {
                "strengths": ["Session completed"],
                "weaknesses": [],
                "suggestions": ["Keep practicing"]
            }

        # 9. DATABASE SAVE (CRITICAL FIXED SECTION)
        print(f"[{request_id}] 💾 Saving DB...")

        try:
            upload_dir = os.path.join("backend", "uploads")
            os.makedirs(upload_dir, exist_ok=True)

            filename = f"{uuid.uuid4()}.wav"
            perm_path = os.path.join(upload_dir, filename)

            shutil.copy(wav_path, perm_path)

            print(f"[{request_id}] 📦 File stored: {perm_path}")

            # Recording
            new_recording = Recording(
                user_id=user.id,
                file_path=perm_path,
                duration=float(round(duration, 2))
            )

            db.add(new_recording)
            db.flush()  # IMPORTANT

            print(f"[{request_id}] 🎧 Recording ID: {new_recording.id}")

            # Analysis
            new_analysis = Analysis(
                recording_id=new_recording.id,
                transcription=text,
                confidence_score=confidence_score,
                emotion=emotion_result["label"],
                word_count=raw_metrics.get("word_count", 0),
                speech_rate=raw_metrics.get("wpm", 0.0),
                filler_words=raw_metrics.get("filler_words", {}).get("total", 0)
            )

            db.add(new_analysis)
            db.commit()

            db.refresh(new_analysis)

            print(f"[{request_id}] ✅ DB SAVED SUCCESSFULLY")
            print(f"[{request_id}] 🧠 Analysis ID: {new_analysis.id}")

        except Exception as db_err:
            db.rollback()
            print(f"[{request_id}] ❌ DB ERROR: {db_err}")
            raise HTTPException(status_code=500, detail=str(db_err))

        # 10. RESPONSE
        print(f"[{request_id}] 🚀 Returning response")

        return SimplifiedAnalysisResponse(
            id=new_analysis.id,
            transcription=text,
            duration=round(duration, 2),
            confidence_score=confidence_score,
            emotion=SimpleEmotionResponse(**emotion_result),
            metrics=SimpleMetrics(
                word_count=raw_metrics.get("word_count", 0),
                speech_rate=raw_metrics.get("wpm", 0.0),
                filler_words=raw_metrics.get("filler_words", {}).get("total", 0)
            ),
            feedback=SimpleCoachingFeedback(**feedback_result),
            created_at=new_analysis.created_at
        )

    except HTTPException:
        raise

    except Exception as e:
        print(f"[{request_id}] 💥 UNEXPECTED ERROR:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        print(f"[{request_id}] 🧹 Cleaning temp files...")

        for path in [tmp_path, wav_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass

        print(f"========== ANALYZE END [{request_id}] ==========\n")


@app.post("/transcribe", tags=["Debug"])
async def debug_transcribe(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Debug endpoint: Only returns transcription text."""
    request_id = str(uuid.uuid4())[:8]
    tmp_path = None
    
    print(f"\n========== POST /transcribe START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    print(f"📥 Input File: {file.filename}")
    
    try:
        print(f"[{request_id}] 📁 Saving file to temp location...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = tmp_file.name
        print(f"[{request_id}] ✅ Temp file created: {tmp_path}")
        
        print(f"[{request_id}] 🎤 Transcribing audio...")
        result = transcription_service.transcribe(tmp_path)
        
        print(f"[{request_id}] ✅ Transcription complete")
        print(f"[{request_id}] 📝 Language: {result.get('language', 'unknown')}")
        print(f"[{request_id}] 📝 Text length: {len(result.get('text', ''))} chars")
        print(f"[{request_id}] ✅ SUCCESS")
        
        return {"text": result["text"], "language": result["language"]}
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /transcribe: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"[{request_id}] 🧹 Cleanup: Removing temp file...")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                print(f"[{request_id}] ✅ Temp file removed")
            except Exception as e:
                print(f"[{request_id}] ⚠ Could not remove temp file: {e}")
        print(f"========== POST /transcribe END [{request_id}] ==========\n")


@app.post("/emotion", tags=["Debug"])
async def debug_emotion(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Debug endpoint: Only returns emotion prediction."""
    request_id = str(uuid.uuid4())[:8]
    tmp_path = None
    
    print(f"\n========== POST /emotion START [{request_id}] ==========")
    print(f"🚀 START")
    print(f"👤 User ID: {user.id}")
    print(f"📥 Input File: {file.filename}")
    
    try:
        print(f"[{request_id}] 📁 Saving file to temp location...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = tmp_file.name
        print(f"[{request_id}] ✅ Temp file created: {tmp_path}")
        
        print(f"[{request_id}] 😊 Detecting emotion...")
        result = emotion_service.detect_emotion(tmp_path)
        
        print(f"[{request_id}] ✅ Emotion detection complete")
        print(f"[{request_id}] 😊 Prediction: {result.get('prediction', 'unknown')}")
        print(f"[{request_id}] 😊 Confidence: {result.get('confidence', 0.0)}")
        print(f"[{request_id}] ✅ SUCCESS")
        
        return result
    except Exception as e:
        print(f"[{request_id}] ❌ ERROR in /emotion: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        print(f"[{request_id}] 🧹 Cleanup: Removing temp file...")
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                print(f"[{request_id}] ✅ Temp file removed")
            except Exception as e:
                print(f"[{request_id}] ⚠ Could not remove temp file: {e}")
        print(f"========== POST /emotion END [{request_id}] ==========\n")
