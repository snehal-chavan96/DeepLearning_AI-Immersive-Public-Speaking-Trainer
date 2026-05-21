import React, { useState, useEffect, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, Square, Mic, Timer, AlertCircle, CheckCircle2, ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Auditorium from '../components/ThreeScene/Auditorium';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import './Practice.css';

export default function Practice() {
  const { 
    isRecording, 
    volume, 
    recordingTime, 
    audioBlob, 
    startRecording, 
    stopRecording 
  } = useAudioRecorder();
  
  const [isFinishing, setIsFinishing] = useState(false);
  const { addToast } = useToast();
  const navigate = useNavigate();

  const { token } = useAuth();

  const handleStart = async () => {
    const success = await startRecording();
    if (success) {
      addToast('Recording started. You are on stage!', 'info', 2000);
    } else {
      addToast('Microphone access denied', 'error');
    }
  };

  const handleStop = () => {
    stopRecording();
    setIsFinishing(true);
    addToast('Finalizing recording...', 'loading', 2000);
  };

  // Navigate only once we have the audioBlob
  useEffect(() => {
    const performAnalysis = async () => {
      if (isFinishing && audioBlob) {
        // Guard against zero-length audio
        if (audioBlob.size < 100) {
          addToast('Recording too short. Please try again.', 'error');
          setIsFinishing(false);
          return;
        }

        addToast('Processing your speech...', 'loading', 5000);
        
        try {
          const formData = new FormData();
          formData.append('file', audioBlob, 'recording.webm');

          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

          console.log('Sending audio to backend...', { size: audioBlob.size, type: audioBlob.type });
          const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
          
          const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`
            },
            body: formData,
            signal: controller.signal
          });

          clearTimeout(timeoutId);

          if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Analysis failed');
          }

          const analysisData = await response.json();
          console.log('Analysis result received:', analysisData);
          
          setIsFinishing(false);
          
          navigate('/analysis', { 
            state: { 
              ...analysisData,
              audioUrl: URL.createObjectURL(audioBlob)
            } 
          });
        } catch (error) {
          console.error('Analysis error:', error);
          const msg = error.name === 'AbortError' ? 'Analysis timed out' : (error.message || 'Analysis failed');
          const finalMsg = response?.status === 500 ? `Analysis engine error: ${msg}` : `${msg}. Please verify your connection.`;
          addToast(finalMsg, 'error');
          setIsFinishing(false);
        }
      }
    };

    performAnalysis();
  }, [isFinishing, audioBlob, navigate, addToast, token]);

  const formatTime = (s) => {
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="practice-page bg-animated-gradient">
      
      {/* 3D Scene */}
      <div className="canvas-container">
        <Suspense fallback={<div className="loading-stage glass-panel">Loading Stage...</div>}>
           <Canvas shadows>
              <Auditorium isPracticeActive={isRecording} volume={volume} />
           </Canvas>
        </Suspense>
      </div>

      {/* Floating HUD Interface */}
      <div className="hud-overlay">
         
         <div className="hud-header">
            <button className="back-btn glass-panel" onClick={() => navigate('/')}>
               <ArrowLeft size={18} />
               <span>Exit Stage</span>
            </button>
            <div className={`status-pill glass-panel ${isRecording ? 'recording' : ''}`}>
               <div className="status-dot"></div>
               <span>{isRecording ? 'LIVE ON STAGE' : 'READY TO START'}</span>
            </div>
         </div>

         <div className="hud-center">
            {!isRecording && !isFinishing && (
              <motion.div 
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="start-hint"
              >
                <h2>Audience is waiting</h2>
                <p>Click start when you are ready to deliver your message.</p>
              </motion.div>
            )}
            {isFinishing && (
              <div className="processing-overlay glass-panel">
                <Mic size={48} className="animate-pulse" color="#ef4444" />
                <h2>Analyzing performance</h2>
                <p>Calculating confidence, clarity, and tone...</p>
              </div>
            )}
         </div>

          <div className="hud-footer">
            <div className="controls-container glass-panel-heavy">
               <div className="timer-display">
                  <div className={`rec-indicator ${isRecording ? 'pulse' : ''}`} />
                  <span className="mono-font">{formatTime(recordingTime)}</span>
               </div>

               <div className="action-buttons">
                  {!isRecording ? (
                    <button className="primary-hud-btn start-btn" onClick={handleStart} disabled={isFinishing}>
                       <Play size={20} fill="currentColor" />
                       <span>ENTER STAGE</span>
                    </button>
                  ) : (
                    <button className="primary-hud-btn stop-btn" onClick={handleStop}>
                       <Square size={18} fill="currentColor" />
                       <span>END SESSION</span>
                    </button>
                  )}
               </div>

               <div className="volume-meter-wrapper">
                  <div className="volume-meter-track">
                     <motion.div 
                        className="volume-meter-bar"
                        animate={{ width: `${volume * 100}%` }}
                        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                     />
                  </div>
               </div>
            </div>
          </div>

      </div>

    </div>
  );
}
