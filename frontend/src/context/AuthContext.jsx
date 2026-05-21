import React, { createContext, useContext, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

const AuthContext = createContext(null);

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token') || null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const checkAuthStatus = async () => {
      if (!token) {
        setIsLoading(false);
        return;
      }

      try {
        console.log(`Checking auth at: ${API_BASE}/me`);
        const response = await fetch(`${API_BASE}/me`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });

        if (response.ok) {
          const userData = await response.json();
          setUser(userData);
        } else {
          console.warn("Session validation failed");
          setUser(null);
          setToken(null);
          localStorage.removeItem('token');
        }
      } catch (error) {
        console.error('Session validation failed:', error);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };

    checkAuthStatus();
  }, [token]);

  const getErrorMessage = (detail) => {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) {
      return detail[0].msg;
    }
    return "An unexpected error occurred.";
  };

  const login = async (email, password) => {
    try {
      console.log(`Sending request: ${API_BASE}/login`);
      const response = await fetch(`${API_BASE}/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ email, password })
      });

      console.log(`Response status: ${response.status}`);
      if (!response.ok) {
        const errorData = await response.json();
        console.error("Login failed:", errorData);
        throw new Error(getErrorMessage(errorData.detail) || "Login failed");
      }

      const data = await response.json();
      localStorage.setItem("token", data.access_token);
      setUser(data.user);
      setToken(data.access_token);

      return true;

    } catch (error) {
      console.error("Fetch error during operation:", error);
      throw error;
    }
  };

  const register = async (name, email, password) => {
    try {
      console.log(`Sending request: ${API_BASE}/signup`);
      const response = await fetch(`${API_BASE}/signup`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ 
          name, 
          email, 
          password,
          confirm_password: password // Backend requires this in RegisterRequest
        })
      });

      console.log(`Response status: ${response.status}`);
      if (!response.ok) {
        const errorData = await response.json();
        console.error("Signup failed:", errorData);
        throw new Error(getErrorMessage(errorData.detail) || "Signup failed");
      }

      const data = await response.json();
      localStorage.setItem("token", data.access_token);
      setUser(data.user);
      setToken(data.access_token);

      return true;

    } catch (error) {
      console.error("Fetch error during operation:", error);
      throw error;
    }
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('token');
    sessionStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
