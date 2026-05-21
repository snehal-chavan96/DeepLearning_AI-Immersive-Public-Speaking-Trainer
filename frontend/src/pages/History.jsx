import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  AreaChart,
  Area
} from 'recharts';
import { Calendar, Filter, Download, MoreVertical } from 'lucide-react';
import DashboardLayout from '../layouts/DashboardLayout';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import './History.css';

export default function History() {
  const { token } = useAuth();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState([]);
  const [trends, setTrends] = useState([]);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        setLoading(true);
        const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
        const response = await fetch(`${API_BASE}/history`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
          const data = await response.json();
          setHistory(data);
          
          // Generate trend data from last 7 sessions
          const trendArray = data.slice(0, 7).reverse().map(item => ({
            day: new Date(item.date).toLocaleDateString('en-US', { weekday: 'short' }),
            score: Math.round(item.score)
          }));
          setTrends(trendArray);
        }
      } catch (err) {
        console.error("Failed to fetch history:", err);
        addToast("Failed to load history", "error");
      } finally {
        setLoading(false);
      }
    };

    if (token) fetchHistory();
  }, [token, addToast]);

  const handleSessionClick = async (sessionId) => {
    try {
      addToast("Loading session details...", "loading");
      const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
      const response = await fetch(`${API_BASE}/analysis/${sessionId}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (response.ok) {
        const detailData = await response.json();
        navigate('/analysis', { state: detailData });
      } else {
        throw new Error("Failed to load details");
      }
    } catch (err) {
      addToast("Could not load session details", "error");
    }
  };

  const formatDuration = (s) => {
    const mins = Math.floor(s / 60);
    const secs = Math.floor(s % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };
  return (
    <DashboardLayout>
      <div className="history-container">
        
        <header className="page-header">
           <div className="header-text">
              <h1 className="display-title">History & Trends</h1>
              <p className="text-secondary">Track your growth across all practice sessions.</p>
           </div>
           <div className="header-tools">
              <button className="tool-btn glass-panel"><Filter size={16} /> Filter</button>
              <button className="tool-btn glass-panel"><Download size={16} /> Export</button>
           </div>
        </header>

        {/* Trend Visualization */}
         <section className="trend-section glass-panel">
            <div className="chart-header">
               <h3>Performance Trend</h3>
               <div className="chart-period">{trends.length > 0 ? `Last ${trends.length} Sessions` : 'No data yet'}</div>
            </div>
            <div className="chart-wrapper" style={{ height: 300 }}>
               {loading ? (
                 <div className="loading-placeholder">Loading chart...</div>
               ) : trends.length > 0 ? (
               <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trends}>
                    <defs>
                       <linearGradient id="colorScore" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="var(--primary)" stopOpacity={0}/>
                       </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                    <XAxis 
                       dataKey="day" 
                       axisLine={false} 
                       tickLine={false} 
                       tick={{ fill: 'var(--text-muted)', fontSize: 12 }} 
                    />
                    <YAxis 
                       hide 
                       domain={[0, 100]} 
                    />
                    <Tooltip 
                       contentStyle={{ 
                          background: 'rgba(17, 24, 39, 0.8)', 
                          border: '1px solid var(--glass-border)',
                          borderRadius: '12px',
                          backdropFilter: 'blur(10px)'
                       }}
                       cursor={{ stroke: 'var(--primary)', strokeWidth: 2 }}
                    />
                    <Area 
                       type="monotone" 
                       dataKey="score" 
                       stroke="var(--primary)" 
                       strokeWidth={3}
                       fillOpacity={1} 
                       fill="url(#colorScore)" 
                       animationDuration={2000}
                    />
                 </AreaChart>
              </ResponsiveContainer>
               ) : (
                 <div className="empty-chart-state glass-panel">
                    <p>Insufficient data for trend analysis. Keep practicing!</p>
                 </div>
               )}
           </div>
        </section>

         <section className="sessions-list-section">
            <div className="section-header">
               <h2>All Sessions</h2>
               <span className="count-badge">{history.length} total</span>
            </div>
            
            <div className="sessions-grid">
               {loading ? (
                 <div className="loading-placeholder">Fetching sessions...</div>
               ) : history.length > 0 ? (
                history.map((session, idx) => (
                 <motion.div 
                   key={session.id}
                   initial={{ opacity: 0, x: -10 }}
                   animate={{ opacity: 1, x: 0 }}
                   transition={{ delay: idx * 0.05 }}
                   className="session-row glass-panel clickable"
                   onClick={() => handleSessionClick(session.id)}
                 >
                    <div className="session-date">
                       <Calendar size={14} />
                       <span>{new Date(session.date).toLocaleDateString()}</span>
                    </div>
                    <div className="session-main">
                       <span className="session-title">{session.title}</span>
                       <span className="session-meta">{formatDuration(session.duration)} • {session.emotion}</span>
                    </div>
                    <div className="session-progress">
                       <div className="progress-bar-bg">
                          <motion.div 
                             className="progress-bar-fill"
                             initial={{ width: 0 }}
                             animate={{ width: `${session.score}%` }}
                             transition={{ duration: 1, delay: 0.5 }}
                             style={{ background: session.score > 80 ? 'var(--success)' : 'var(--primary)' }}
                          />
                       </div>
                       <span className="session-score-text">{Math.round(session.score)}%</span>
                    </div>
                    <button className="session-more">
                       <MoreVertical size={18} />
                    </button>
                 </motion.div>
                ))
               ) : (
                 <div className="empty-state glass-panel">
                    <Calendar size={48} opacity={0.2} />
                    <p>No practice sessions recorded yet.</p>
                 </div>
               )}
            </div>
         </section>

      </div>
    </DashboardLayout>
  );
}
