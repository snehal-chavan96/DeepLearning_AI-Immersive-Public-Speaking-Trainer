import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Play, TrendingUp, Award, Clock, ArrowRight, Mic2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../layouts/DashboardLayout';
import { useAuth } from '../context/AuthContext';
import './Home.css';

export default function Home() {
  const { token } = useAuth();
  const [loading, setLoading] = useState(true);
  const [dashboardData, setDashboardData] = useState({
    stats: [],
    recentSessions: []
  });

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
        const [statsRes, historyRes] = await Promise.all([
          fetch(`${API_BASE}/stats`, { headers: { 'Authorization': `Bearer ${token}` } }),
          fetch(`${API_BASE}/history`, { headers: { 'Authorization': `Bearer ${token}` } })
        ]);

        if (statsRes.ok && historyRes.ok) {
          const statsData = await statsRes.json();
          const historyData = await historyRes.json();

          const formattedStats = [
            { label: 'Avg Confidence', value: `${statsData.avg_confidence}%`, icon: Award, color: '#4f46e5' },
            { label: 'Speeches', value: String(statsData.total_speeches), icon: Mic2, color: '#10b981' },
            { label: 'Hours', value: `${statsData.total_hours}h`, icon: Clock, color: '#f59e0b' },
            { label: 'Improvement', value: `+${statsData.improvement}%`, icon: TrendingUp, color: '#ec4899' },
          ];

          setDashboardData({
            stats: formattedStats,
            recentSessions: historyData.slice(0, 3) // Only show latest 3
          });
        }
      } catch (err) {
        console.error("Failed to fetch dashboard data:", err);
      } finally {
        setLoading(false);
      }
    };

    if (token) fetchData();
  }, [token]);

  const { stats, recentSessions } = dashboardData;

  return (
    <DashboardLayout>
      <div className="home-container">
        
        {/* Welcome Section */}
        <section className="welcome-section">
          <motion.div 
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="welcome-info"
          >
            <h1 className="display-title">Ready to take the stage?</h1>
            <p className="text-secondary subtitle">Master your presence with AI-guided practice sessions.</p>
          </motion.div>
          
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            whileHover={{ scale: 1.02 }}
            className="main-cta-card glass-panel"
          >
            <div className="cta-content">
               <div className="cta-icon-bg">
                  <Play fill="white" size={32} />
               </div>
               <div className="cta-text">
                  <h3>Start Practice Session</h3>
                  <p>Step into the virtual auditorium</p>
               </div>
            </div>
            <Link to="/practice" className="cta-arrow">
               <ArrowRight size={24} />
            </Link>
          </motion.div>
        </section>

        {/* Stats Grid */}
        <section className="stats-section">
          <h2 className="section-title">Your Progress</h2>
          <div className="stats-grid">
            {stats.map((stat, idx) => (
              <motion.div 
                key={stat.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="stat-card glass-panel"
              >
                <div className="stat-icon" style={{ background: `${stat.color}15`, color: stat.color }}>
                  <stat.icon size={20} />
                </div>
                <div className="stat-data">
                  <span className="stat-value">{stat.value}</span>
                  <span className="stat-label">{stat.label}</span>
                </div>
              </motion.div>
            ))}
          </div>
        </section>

        {/* Recent & Recommendations */}
        <div className="dashboard-grid">
           <section className="recent-sessions-section glass-panel">
              <div className="panel-header">
                 <h2 className="section-title">Recent Activity</h2>
                 <Link to="/history" className="view-all">View all</Link>
              </div>
              <div className="sessions-list">
                 {loading ? (
                    <div className="loading-placeholder">Loading recent activity...</div>
                 ) : recentSessions.length > 0 ? (
                   recentSessions.map((session) => (
                    <div key={session.id} className="session-item">
                       <div className="session-info">
                          <span className="session-title">{session.title}</span>
                          <span className="session-meta">
                            {new Date(session.date).toLocaleDateString()} • {session.emotion}
                          </span>
                       </div>
                       <div className="session-score">
                          <div className="score-badge" style={{ 
                            background: session.score > 80 ? 'var(--success-glow)' : 'rgba(255,255,255,0.05)',
                            color: session.score > 80 ? 'var(--success)' : 'var(--text-secondary)'
                          }}>
                             {Math.round(session.score)}
                          </div>
                       </div>
                    </div>
                   ))
                 ) : (
                   <div className="empty-sessions">No sessions yet. Time to practice!</div>
                 )}
              </div>
           </section>

           <section className="recommendation-card glass-panel">
              <h2 className="section-title">AI Insight</h2>
              <p className="insight-text">
                "Based on your last interview pitch, you tend to use 'umm' and 'ah' during transitions. Try taking a purposeful pause instead."
              </p>
              <div className="insight-action">
                 <button className="secondary-btn">View Lesson</button>
              </div>
           </section>
        </div>

      </div>
    </DashboardLayout>
  );
}
