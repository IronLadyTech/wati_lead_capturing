import React, { useState, useEffect, useCallback } from 'react';
import './App.css';

// API Base URL
const API_URL = "https://wati-leads-dashboard.iamironlady.com";

// ============================================
// SIMPLE BAR CHART COMPONENT
// ============================================
const SimpleBarChart = ({ data }) => {
  const maxValue = Math.max(...data.map(d => d.clicks), 1);
  
  return (
    <div className="simple-chart">
      <div className="chart-bars">
        {data.map((item, idx) => (
          <div key={idx} className="chart-bar-container">
            <div className="chart-bar-wrapper">
              <div 
                className="chart-bar" 
                style={{ height: `${(item.clicks / maxValue) * 100}%` }}
              >
                <span className="chart-bar-value">{item.clicks}</span>
              </div>
            </div>
            <span className="chart-bar-label">{item.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

// ============================================
// HELPER FUNCTIONS
// ============================================
const formatDate = (dateString) => {
  if (!dateString) return '-';
  try {
    const date = new Date(dateString);
    return date.toLocaleString('en-IN', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return '-';
  }
};

const getStatusBadgeClass = (status) => {
  switch (status) {
    case 'pending': return 'status-pending';
    case 'in_progress': return 'status-in-progress';
    case 'resolved': return 'status-resolved';
    default: return 'status-pending';
  }
};

const getStatusIcon = (status) => {
  switch (status) {
    case 'pending': return '🟡';
    case 'in_progress': return '🔵';
    case 'resolved': return '✅';
    default: return '⚪';
  }
};

// ============================================
// TICKET DETAIL MODAL WITH CONVERSATION
// ============================================
const TicketDetailModal = ({ isOpen, onClose, ticketId, onTicketUpdate }) => {
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

  const fetchTicketDetails = useCallback(async () => {
    if (!ticketId) return;
    
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/tickets/${ticketId}`);
      const data = await res.json();
      setTicket(data);
      setLoading(false);
    } catch (err) {
      console.error(err);
      setError('Failed to load ticket details');
      setLoading(false);
    }
  }, [ticketId]);

  useEffect(() => {
    if (isOpen && ticketId) {
      fetchTicketDetails();
    }
  }, [isOpen, ticketId, fetchTicketDetails]);

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    
    setSending(true);
    setError(null);
    
    try {
      const res = await fetch(`${API_URL}/api/tickets/${ticketId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: replyText,
          counsellor_name: 'Counsellor'
        })
      });
      
      const data = await res.json();
      
      if (res.ok && data.success) {
        setReplyText('');
        fetchTicketDetails(); // Refresh conversation
        if (onTicketUpdate) onTicketUpdate();
      } else {
        setError(data.detail || 'Failed to send reply');
      }
    } catch (err) {
      console.error(err);
      setError('Failed to send reply. Please try again.');
    }
    
    setSending(false);
  };

  const handleStatusChange = async (newStatus) => {
    try {
      const res = await fetch(`${API_URL}/api/tickets/${ticketId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: newStatus,
          resolved_by: 'Counsellor'
        })
      });
      
      if (res.ok) {
        fetchTicketDetails();
        if (onTicketUpdate) onTicketUpdate();
      }
    } catch (err) {
      console.error(err);
      setError('Failed to update status');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container modal-ticket" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🎫 {ticket?.ticket?.ticket_number || 'Loading...'}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        
        {loading ? (
          <div className="modal-body">
            <div className="loading">Loading ticket details...</div>
          </div>
        ) : ticket ? (
          <>
            {/* Ticket Info Bar */}
            <div className="ticket-info-bar">
              <div className="ticket-info-item">
                <span className="info-label">Category:</span>
                <span className={`category-badge category-${ticket.ticket.category}`}>
                  {ticket.ticket.category === 'query' ? '❓ Query' : '⚠️ Concern'}
                </span>
              </div>
              <div className="ticket-info-item">
                <span className="info-label">Status:</span>
                <span className={`status-badge-large ${getStatusBadgeClass(ticket.ticket.status)}`}>
                  {getStatusIcon(ticket.ticket.status)} {ticket.ticket.status.replace('_', ' ')}
                </span>
              </div>
              <div className="ticket-info-item">
                <span className="info-label">24hr Window:</span>
                <span className={`window-badge ${ticket.ticket.is_24hr_active ? 'window-active' : 'window-expired'}`}>
                  {ticket.ticket.is_24hr_active 
                    ? `✅ Active (${ticket.ticket.hours_remaining}h left)` 
                    : '❌ Expired'}
                </span>
              </div>
            </div>

            {/* User Info */}
            <div className="ticket-user-info">
              <div className="user-info-row">
                <span className="user-icon">👤</span>
                <span className="user-name">{ticket.user.name || 'Unknown'}</span>
                <a href={`tel:${ticket.user.phone_number}`} className="contact-btn phone-btn">
                  📞 {ticket.user.phone_number}
                </a>
                <a 
                  href={`https://wa.me/${ticket.user.phone_number}`} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="contact-btn whatsapp-btn-small"
                >
                  💬 WhatsApp
                </a>
              </div>
              {ticket.user.email && (
                <div className="user-email">✉️ {ticket.user.email}</div>
              )}
              <div className="ticket-dates">
                <span>Created: {formatDate(ticket.ticket.created_at)}</span>
                {ticket.ticket.resolved_at && (
                  <span> | Resolved: {formatDate(ticket.ticket.resolved_at)}</span>
                )}
              </div>
            </div>

            {/* Conversation Thread */}
            <div className="conversation-container">
              <h3 className="conversation-title">💬 Conversation</h3>
              <div className="messages-list">
                {ticket.messages.length === 0 ? (
                  <div className="no-messages">No messages yet</div>
                ) : (
                  ticket.messages.map((msg, idx) => (
                    <div 
                      key={idx} 
                      className={`message-bubble ${msg.direction === 'incoming' ? 'message-incoming' : 'message-outgoing'}`}
                    >
                      <div className="message-header">
                        <span className="message-sender">
                          {msg.direction === 'incoming' ? '👤 User' : `🎧 ${msg.sent_by || 'Counsellor'}`}
                        </span>
                        <span className="message-time">{formatDate(msg.created_at)}</span>
                      </div>
                      <div className="message-content">
                        {msg.message_text}
                      </div>
                      {msg.media_url && (
                        <div className="message-media">
                          <a href={msg.media_url} target="_blank" rel="noopener noreferrer">
                            📎 {msg.media_filename || 'View Attachment'}
                          </a>
                        </div>
                      )}
                      {msg.direction === 'outgoing' && (
                        <div className="message-status">
                          {msg.delivery_status === 'sent' && '✓ Sent'}
                          {msg.delivery_status === 'delivered' && '✓✓ Delivered'}
                          {msg.delivery_status === 'read' && '✓✓ Read'}
                          {msg.delivery_status === 'failed' && '❌ Failed'}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Reply Section */}
            {ticket.ticket.status !== 'resolved' && (
              <div className="reply-section">
                {error && <div className="error-message">{error}</div>}
                
                {!ticket.ticket.is_24hr_active ? (
                  <div className="window-expired-warning">
                    ⚠️ 24-hour window has expired. You cannot send session messages.
                    <br />
                    Please contact the user via personal WhatsApp or wait for them to message again.
                  </div>
                ) : (
                  <>
                    <textarea
                      className="reply-textarea"
                      placeholder="Type your reply here..."
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      rows={3}
                      disabled={sending}
                    />
                    <div className="reply-actions">
                      <button 
                        className="btn btn-primary"
                        onClick={handleSendReply}
                        disabled={sending || !replyText.trim()}
                      >
                        {sending ? '📤 Sending...' : '📤 Send Reply'}
                      </button>
                      <span className="reply-note">
                        ℹ️ User will receive satisfaction buttons with your reply
                      </span>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Footer Actions */}
            <div className="modal-footer ticket-footer">
              {ticket.ticket.status !== 'resolved' && (
                <button 
                  className="btn btn-resolve"
                  onClick={() => handleStatusChange('resolved')}
                >
                  ✅ Mark as Resolved
                </button>
              )}
              {ticket.ticket.status === 'resolved' && (
                <button 
                  className="btn btn-reopen"
                  onClick={() => handleStatusChange('pending')}
                >
                  🔄 Reopen Ticket
                </button>
              )}
              <a 
                href={`https://wa.me/${ticket.user.phone_number}`} 
                target="_blank" 
                rel="noopener noreferrer"
                className="btn btn-whatsapp"
              >
                💬 Open WhatsApp
              </a>
            </div>
          </>
        ) : (
          <div className="modal-body">
            <div className="error">Failed to load ticket</div>
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================
// USER DETAIL MODAL
// ============================================
const UserDetailModal = ({ isOpen, onClose, userId }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen && userId) {
      setLoading(true);
      fetch(`${API_URL}/api/users/${userId}`)
        .then(res => res.json())
        .then(data => {
          setUser(data.user);
          setLoading(false);
        })
        .catch(err => {
          console.error(err);
          setLoading(false);
        });
    }
  }, [isOpen, userId]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container modal-large" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>👤 User Details</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {loading ? (
            <div className="loading">Loading...</div>
          ) : user ? (
            <div className="user-details-grid">
              <div className="detail-card">
                <h3>📋 Basic Information</h3>
                <div className="detail-row">
                  <span className="detail-label">Name:</span>
                  <span className="detail-value">{user.name || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Email:</span>
                  <span className="detail-value">{user.email || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Phone:</span>
                  <span className="detail-value">{user.phone_number || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Participation:</span>
                  <span className="detail-value">{user.participation_level || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Enrolled Program:</span>
                  <span className="detail-value">{user.enrolled_program || '-'}</span>
                </div>
              </div>
              <div className="detail-card">
                <h3>📊 Activity</h3>
                <div className="detail-row">
                  <span className="detail-label">First Seen:</span>
                  <span className="detail-value">{formatDate(user.first_seen)}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Last Active:</span>
                  <span className="detail-value">{formatDate(user.last_interaction)}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Active Ticket:</span>
                  <span className="detail-value">{user.has_active_ticket ? 'Yes' : 'No'}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="error">User not found</div>
          )}
        </div>
        {user && (
          <div className="modal-footer">
            <a href={`tel:${user.phone_number}`} className="btn btn-call">📞 Call</a>
            <a href={`https://wa.me/${user.phone_number}`} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp">💬 WhatsApp</a>
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================
// TICKETS VIEW COMPONENT (QUERIES & CONCERNS)
// ============================================
const TicketsView = () => {
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all'); // all, queries, concerns
  const [statusFilter, setStatusFilter] = useState('all'); // all, pending, in_progress, resolved
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTicketId, setSelectedTicketId] = useState(null);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    try {
      let url = `${API_URL}/api/tickets?limit=500`;
      
      if (statusFilter !== 'all') {
        url += `&status=${statusFilter}`;
      }
      if (activeTab === 'queries') {
        url += '&category=query';
      } else if (activeTab === 'concerns') {
        url += '&category=concern';
      }
      
      const res = await fetch(url);
      const data = await res.json();
      setTickets(data.tickets || []);
      setStats(data.stats || {});
      setLoading(false);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  }, [activeTab, statusFilter]);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  // Filter tickets by search
  const filteredTickets = tickets.filter(t => {
    if (!searchTerm) return true;
    const search = searchTerm.toLowerCase();
    return (
      (t.ticket_number || '').toLowerCase().includes(search) ||
      (t.user_name || '').toLowerCase().includes(search) ||
      (t.user_phone || '').toLowerCase().includes(search) ||
      (t.initial_message || '').toLowerCase().includes(search)
    );
  });

  return (
    <div className="view-container">
      <div className="view-header">
        <h2>🎫 Support Tickets</h2>
      </div>

      {/* Stats Bar */}
      {stats && (
        <div className="ticket-stats-bar">
          <div className="ticket-stat">
            <span className="ticket-stat-number">{stats.total}</span>
            <span className="ticket-stat-label">Total</span>
          </div>
          <div className="ticket-stat ticket-stat-pending">
            <span className="ticket-stat-number">{stats.pending}</span>
            <span className="ticket-stat-label">Pending</span>
          </div>
          <div className="ticket-stat ticket-stat-progress">
            <span className="ticket-stat-number">{stats.in_progress}</span>
            <span className="ticket-stat-label">In Progress</span>
          </div>
          <div className="ticket-stat ticket-stat-resolved">
            <span className="ticket-stat-number">{stats.resolved}</span>
            <span className="ticket-stat-label">Resolved</span>
          </div>
          <div className="ticket-stat ticket-stat-queries">
            <span className="ticket-stat-number">{stats.queries}</span>
            <span className="ticket-stat-label">Queries</span>
          </div>
          <div className="ticket-stat ticket-stat-concerns">
            <span className="ticket-stat-number">{stats.concerns}</span>
            <span className="ticket-stat-label">Concerns</span>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="tabs-container">
        <button
          className={`tab-btn ${activeTab === 'all' ? 'active' : ''}`}
          onClick={() => setActiveTab('all')}
        >
          📋 All Tickets
        </button>
        <button
          className={`tab-btn ${activeTab === 'queries' ? 'active' : ''}`}
          onClick={() => setActiveTab('queries')}
        >
          ❓ Queries
        </button>
        <button
          className={`tab-btn ${activeTab === 'concerns' ? 'active' : ''}`}
          onClick={() => setActiveTab('concerns')}
        >
          ⚠️ Concerns
        </button>
      </div>

      {/* Filters */}
      <div className="ticket-filters">
        <div className="filter-group">
          <label>Status:</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All Status</option>
            <option value="pending">🟡 Pending</option>
            <option value="in_progress">🔵 In Progress</option>
            <option value="resolved">✅ Resolved</option>
          </select>
        </div>
        <div className="filter-group search-group">
          <label>Search:</label>
          <input
            type="text"
            placeholder="Search ticket, name, phone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <button className="btn btn-refresh" onClick={fetchTickets}>
          🔄 Refresh
        </button>
      </div>

      {/* Tickets List */}
      {loading ? (
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading tickets...</p>
        </div>
      ) : (
        <div className="tickets-list">
          {filteredTickets.length === 0 ? (
            <div className="no-data-card">
              <p>No tickets found</p>
            </div>
          ) : (
            filteredTickets.map(ticket => (
              <div 
                key={ticket.id} 
                className={`ticket-card ticket-${ticket.status}`}
                onClick={() => setSelectedTicketId(ticket.id)}
              >
                <div className="ticket-card-header">
                  <div className="ticket-number-section">
                    <span className="ticket-number">{ticket.ticket_number}</span>
                    <span className={`category-badge category-${ticket.category}`}>
                      {ticket.category === 'query' ? '❓ Query' : '⚠️ Concern'}
                    </span>
                  </div>
                  <div className="ticket-status-section">
                    <span className={`status-badge ${getStatusBadgeClass(ticket.status)}`}>
                      {getStatusIcon(ticket.status)} {ticket.status.replace('_', ' ')}
                    </span>
                    {ticket.is_24hr_active ? (
                      <span className="window-indicator window-active" title="24hr window active">
                        ⏰ {ticket.hours_remaining}h
                      </span>
                    ) : (
                      <span className="window-indicator window-expired" title="24hr window expired">
                        ⏰ Expired
                      </span>
                    )}
                  </div>
                </div>
                
                <div className="ticket-card-body">
                  <div className="ticket-user">
                    <span className="user-name">👤 {ticket.user_name || 'Unknown'}</span>
                    <span className="user-phone">📱 {ticket.user_phone}</span>
                  </div>
                  <div className="ticket-message">
                    {ticket.initial_message.length > 150 
                      ? ticket.initial_message.substring(0, 150) + '...' 
                      : ticket.initial_message}
                  </div>
                </div>
                
                <div className="ticket-card-footer">
                  <span className="ticket-date">📅 {formatDate(ticket.created_at)}</span>
                  <span className="ticket-messages">💬 {ticket.message_count} messages</span>
                  <button className="btn btn-view" onClick={(e) => {
                    e.stopPropagation();
                    setSelectedTicketId(ticket.id);
                  }}>
                    View & Reply →
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Ticket Detail Modal */}
      <TicketDetailModal
        isOpen={selectedTicketId !== null}
        onClose={() => setSelectedTicketId(null)}
        ticketId={selectedTicketId}
        onTicketUpdate={fetchTickets}
      />
    </div>
  );
};

// ============================================
// STATS CARDS COMPONENT
// ============================================
const StatsCards = ({ users }) => {
  const totalLeads = users.length;
  const newUsers = users.filter(u => u.participation_level === 'New to platform').length;
  const enrolled = users.filter(u => u.participation_level === 'Enrolled Participant').length;
  const withActiveTickets = users.filter(u => u.has_active_ticket).length;

  return (
    <div className="stats-grid">
      <div className="stat-card stat-total">
        <div className="stat-icon">📊</div>
        <div className="stat-content">
          <div className="stat-number">{totalLeads}</div>
          <div className="stat-label">Total Leads</div>
        </div>
      </div>
      <div className="stat-card stat-new">
        <div className="stat-icon">🆕</div>
        <div className="stat-content">
          <div className="stat-number">{newUsers}</div>
          <div className="stat-label">New Users</div>
        </div>
      </div>
      <div className="stat-card stat-enrolled">
        <div className="stat-icon">✅</div>
        <div className="stat-content">
          <div className="stat-number">{enrolled}</div>
          <div className="stat-label">Enrolled</div>
        </div>
      </div>
      <div className="stat-card stat-counsellor">
        <div className="stat-icon">🎫</div>
        <div className="stat-content">
          <div className="stat-number">{withActiveTickets}</div>
          <div className="stat-label">Active Tickets</div>
        </div>
      </div>
    </div>
  );
};

// ============================================
// ACTION BUTTONS COMPONENT
// ============================================
const ActionButtons = ({ activeView, setActiveView }) => {
  return (
    <div className="action-buttons-section">
      <button 
        className={`action-btn ${activeView === 'tickets' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'tickets' ? 'leads' : 'tickets')}
      >
        <span className="action-icon">🎫</span>
        <span>View Tickets</span>
      </button>
      <button 
        className={`action-btn ${activeView === 'feedbacks' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'feedbacks' ? 'leads' : 'feedbacks')}
      >
        <span className="action-icon">💬</span>
        <span>View Feedbacks</span>
      </button>
      <button 
        className={`action-btn ${activeView === 'courses' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'courses' ? 'leads' : 'courses')}
      >
        <span className="action-icon">📚</span>
        <span>Course Interests</span>
      </button>
      <button 
        className={`action-btn ${activeView === 'broadcast' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'broadcast' ? 'leads' : 'broadcast')}
      >
        <span className="action-icon">📢</span>
        <span>Broadcast Status</span>
      </button>
      {activeView !== 'leads' && (
        <button 
          className="action-btn action-btn-back"
          onClick={() => setActiveView('leads')}
        >
          <span className="action-icon">👥</span>
          <span>Back to Leads</span>
        </button>
      )}
    </div>
  );
};

// ============================================
// COURSE INTERESTS VIEW COMPONENT
// ============================================
const CourseInterestsView = () => {
  const [courseData, setCourseData] = useState([]);
  const [courseUsers, setCourseUsers] = useState({});
  const [activeTab, setActiveTab] = useState('overview');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCourseData();
  }, []);

  const fetchCourseData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/course-interests`);
      const data = await res.json();
      setCourseData(data.course_interests || []);
      setLoading(false);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  };

  const fetchCourseUsers = async (courseName) => {
    if (courseUsers[courseName]) return;
    try {
      const res = await fetch(`${API_URL}/api/course-interests/${courseName}`);
      const data = await res.json();
      setCourseUsers(prev => ({ ...prev, [courseName]: data.users || [] }));
    } catch (err) {
      console.error(err);
    }
  };

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab !== 'overview') {
      fetchCourseUsers(tab);
    }
  };

  const tabs = ['overview', 'LEP', '100BM', 'MBW', 'Masterclass'];

  const chartData = courseData.map(c => ({
    name: c.course_name,
    clicks: c.total_clicks,
    users: c.unique_users
  }));

  if (loading) {
    return (
      <div className="view-container">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading course interests...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="view-container">
      <div className="view-header">
        <h2>📚 Course Interests</h2>
      </div>

      <div className="tabs-container">
        {tabs.map(tab => (
          <button
            key={tab}
            className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
            onClick={() => handleTabChange(tab)}
          >
            {tab === 'overview' ? '📊 Overview' : tab}
          </button>
        ))}
      </div>

      {activeTab === 'overview' ? (
        <div className="course-overview">
          <div className="course-overview-content">
            <div className="course-table-container">
              <table className="course-table">
                <thead>
                  <tr>
                    <th>Course</th>
                    <th>Total Clicks</th>
                    <th>Unique Users</th>
                  </tr>
                </thead>
                <tbody>
                  {courseData.map((course, idx) => (
                    <tr key={idx}>
                      <td className="course-name-cell">{course.course_name}</td>
                      <td className="number-cell">{course.total_clicks}</td>
                      <td className="number-cell">{course.unique_users}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="course-chart-container">
              <h4 className="chart-title">Total Clicks by Course</h4>
              <SimpleBarChart data={chartData} />
            </div>
          </div>
        </div>
      ) : (
        <div className="course-users-view">
          <div className="course-info-header">
            <h3>{activeTab} - Interested Users</h3>
            <span className="user-count">
              {courseUsers[activeTab]?.length || 0} users
            </span>
          </div>
          
          {courseUsers[activeTab] ? (
            <div className="course-users-table-container">
              <table className="leads-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Click Count</th>
                    <th>First Clicked</th>
                    <th>Last Clicked</th>
                  </tr>
                </thead>
                <tbody>
                  {courseUsers[activeTab].length === 0 ? (
                    <tr>
                      <td colSpan="6" className="no-data">No users interested in this course yet</td>
                    </tr>
                  ) : (
                    courseUsers[activeTab].map((user, idx) => (
                      <tr key={idx}>
                        <td>{user.name || '-'}</td>
                        <td>{user.email || '-'}</td>
                        <td className="phone-cell">
                          {user.phone_number ? (
                            <>
                              <a href={`tel:${user.phone_number}`} className="icon-btn" title="Call">📞</a>
                              <span>{user.phone_number}</span>
                              <a 
                                href={`https://wa.me/${user.phone_number}`} 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="whatsapp-btn"
                                title="WhatsApp"
                              >
                                💬
                              </a>
                            </>
                          ) : '-'}
                        </td>
                        <td className="number-cell">{user.click_count}</td>
                        <td>{formatDate(user.first_clicked)}</td>
                        <td>{formatDate(user.last_clicked)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="loading">Loading users...</div>
          )}
        </div>
      )}
    </div>
  );
};

// ============================================
// FEEDBACKS VIEW COMPONENT
// ============================================
const FeedbacksView = () => {
  const [feedbacks, setFeedbacks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchFeedbacks();
  }, []);

  const fetchFeedbacks = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/feedbacks`);
      const data = await res.json();
      setFeedbacks(data.feedbacks || []);
      setLoading(false);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="view-container">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading feedbacks...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="view-container">
      <div className="view-header">
        <h2>💬 All Feedbacks</h2>
      </div>

      <div className="feedback-count-bar">
        <span>📊 Total Feedbacks: <strong>{feedbacks.length}</strong></span>
      </div>

      <div className="feedbacks-list">
        {feedbacks.length === 0 ? (
          <div className="no-data-card">
            <p>No feedbacks recorded yet</p>
          </div>
        ) : (
          feedbacks.map((feedback, idx) => (
            <div key={idx} className="feedback-card">
              <div className="feedback-card-header">
                <div className="feedback-user-info">
                  <span className="feedback-user-name">{feedback.user_name || 'Unknown'}</span>
                  <span className="feedback-date">{formatDate(feedback.created_at)}</span>
                </div>
              </div>
              
              <div className="feedback-card-body">
                <div className="feedback-contact-row">
                  <div className="feedback-contact-item">
                    <a href={`tel:${feedback.user_phone}`} className="contact-link phone-link">
                      📞 {feedback.user_phone}
                    </a>
                    <a 
                      href={`https://wa.me/${feedback.user_phone}`} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="whatsapp-badge"
                    >
                      WhatsApp
                    </a>
                  </div>
                  {feedback.user_email && (
                    <div className="feedback-contact-item">
                      <a href={`mailto:${feedback.user_email}`} className="contact-link email-link">
                        ✉️ {feedback.user_email}
                      </a>
                    </div>
                  )}
                </div>
                
                <div className="feedback-text-container">
                  <span className="feedback-label">Feedback:</span>
                  <p className="feedback-text">{feedback.feedback_text}</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ============================================
// BROADCAST STATUS VIEW COMPONENT
// ============================================
const BroadcastStatusView = () => {
  const [stats, setStats] = useState(null);
  const [failedMessages, setFailedMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    fetchBroadcastData();
  }, []);

  const fetchBroadcastData = async () => {
    setLoading(true);
    try {
      const [statsRes, failedRes] = await Promise.all([
        fetch(`${API_URL}/api/broadcasts/stats`),
        fetch(`${API_URL}/api/broadcasts/failed`)
      ]);
      
      const statsData = await statsRes.json();
      const failedData = await failedRes.json();
      
      setStats(statsData);
      setFailedMessages(failedData.failed_broadcasts || []);
      setLoading(false);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  };

  const handleSendViaWhatsApp = (phone, message) => {
    const cleanPhone = phone.replace(/[^0-9]/g, '');
    const encodedMessage = encodeURIComponent(message);
    const url = `https://wa.me/${cleanPhone}?text=${encodedMessage}`;
    window.open(url, '_blank');
  };

  const handleCopyMessage = (message) => {
    navigator.clipboard.writeText(message);
    alert('Message copied to clipboard!');
  };

  const handleMarkAsSent = async (broadcastId) => {
    try {
      await fetch(`${API_URL}/api/broadcasts/${broadcastId}/mark-resent`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manually_sent_by: 'Dashboard User' })
      });
      
      fetchBroadcastData();
      alert('Marked as manually sent!');
    } catch (err) {
      console.error(err);
      alert('Failed to update status');
    }
  };

  const filteredMessages = failedMessages.filter(msg => {
    if (!searchTerm) return true;
    const search = searchTerm.toLowerCase();
    const name = (msg.recipient_name || '').toLowerCase();
    const phone = (msg.phone_number || '').toLowerCase();
    const message = (msg.message_text || '').toLowerCase();
    
    return name.includes(search) || phone.includes(search) || message.includes(search);
  });

  if (loading) {
    return (
      <div className="view-container">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading broadcast data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="view-container">
      <div className="view-header">
        <h2>📢 Broadcast Status</h2>
      </div>

      {stats && (
        <div className="broadcast-stats">
          <div className="broadcast-stat-card stat-total">
            <div className="broadcast-stat-icon">📊</div>
            <div className="broadcast-stat-content">
              <div className="broadcast-stat-number">{stats.total}</div>
              <div className="broadcast-stat-label">Total Sent</div>
            </div>
          </div>
          <div className="broadcast-stat-card stat-delivered">
            <div className="broadcast-stat-icon">✅</div>
            <div className="broadcast-stat-content">
              <div className="broadcast-stat-number">{stats.delivered}</div>
              <div className="broadcast-stat-label">Delivered</div>
            </div>
          </div>
          <div className="broadcast-stat-card stat-failed">
            <div className="broadcast-stat-icon">❌</div>
            <div className="broadcast-stat-content">
              <div className="broadcast-stat-number">{stats.failed}</div>
              <div className="broadcast-stat-label">Failed</div>
            </div>
          </div>
          <div className="broadcast-stat-card stat-manual">
            <div className="broadcast-stat-icon">📱</div>
            <div className="broadcast-stat-content">
              <div className="broadcast-stat-number">{stats.manually_sent}</div>
              <div className="broadcast-stat-label">Manually Sent</div>
            </div>
          </div>
        </div>
      )}

      <div className="broadcast-filters">
        <div className="broadcast-search-group">
          <label>🔍 Search Failed Messages</label>
          <input
            type="text"
            placeholder="Search name, phone, or message..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <button className="btn btn-refresh" onClick={fetchBroadcastData}>
          🔄 Refresh
        </button>
      </div>

      <div className="failed-messages-header">
        <h3>❌ Failed Messages ({filteredMessages.length})</h3>
      </div>

      <div className="failed-messages-list">
        {filteredMessages.length === 0 ? (
          <div className="no-failed-messages">
            <p>🎉 No failed messages!</p>
          </div>
        ) : (
          filteredMessages.map((msg, idx) => (
            <div key={idx} className="failed-message-card">
              <div className="failed-message-header">
                <div className="failed-message-user">
                  <span className="failed-message-name">{msg.recipient_name || 'Unknown'}</span>
                  <span className="failed-message-phone">📱 {msg.phone_number}</span>
                </div>
                <div className="failed-message-meta">
                  <span className="failed-message-date">📅 {formatDate(msg.failed_at || msg.sent_at)}</span>
                </div>
              </div>

              <div className="failed-message-body">
                <div className="failed-message-text">
                  <span className="failed-message-label">Message:</span>
                  <p>{msg.message_text}</p>
                </div>

                {msg.failure_reason && (
                  <div className="failed-message-reason">
                    <span className="failed-message-label">⚠️ Failure Reason:</span>
                    <p>{msg.failure_reason}</p>
                  </div>
                )}
              </div>

              <div className="failed-message-actions">
                <button 
                  className="btn btn-whatsapp"
                  onClick={() => handleSendViaWhatsApp(msg.phone_number, msg.message_text)}
                >
                  💬 Send via WhatsApp
                </button>
                <button 
                  className="btn btn-secondary"
                  onClick={() => handleCopyMessage(msg.message_text)}
                >
                  📋 Copy Message
                </button>
                <button 
                  className="btn btn-resolve"
                  onClick={() => handleMarkAsSent(msg.id)}
                >
                  ✅ Mark as Sent
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ============================================
// MAIN APP COMPONENT
// ============================================
function App() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeView, setActiveView] = useState('leads');
  
  // Filters
  const [timeFilter, setTimeFilter] = useState('All');
  const [participationFilter, setParticipationFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  
  // Modals
  const [userModal, setUserModal] = useState({ isOpen: false, userId: null });

  // Fetch data
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_URL}/api/users`);
        const data = await res.json();
        setUsers(data.users || []);
        setError(null);
      } catch (err) {
        setError('Failed to fetch data. Make sure backend is running.');
        console.error(err);
      }
      setLoading(false);
    };

    fetchData();
  }, []);

  // Filter users
  const filteredUsers = users.filter(user => {
    // Time filter
    if (timeFilter !== 'All') {
      const userDate = new Date(user.first_seen);
      const now = new Date();
      let daysAgo = 0;
      
      switch (timeFilter) {
        case 'Today': daysAgo = 1; break;
        case 'Last 2 Days': daysAgo = 2; break;
        case 'Last 3 Days': daysAgo = 3; break;
        case 'Last Week': daysAgo = 7; break;
        case 'Last 2 Weeks': daysAgo = 14; break;
        case 'Last Month': daysAgo = 30; break;
        default: daysAgo = 0;
      }
      
      if (daysAgo > 0) {
        const cutoff = new Date(now.getTime() - daysAgo * 24 * 60 * 60 * 1000);
        if (userDate < cutoff) return false;
      }
    }
    
    // Participation filter
    if (participationFilter !== 'All' && user.participation_level !== participationFilter) {
      return false;
    }
    
    // Search filter
    if (searchTerm) {
      const search = searchTerm.toLowerCase();
      const name = (user.name || '').toLowerCase();
      const email = (user.email || '').toLowerCase();
      const phone = (user.phone_number || '').toLowerCase();
      if (!name.includes(search) && !email.includes(search) && !phone.includes(search)) {
        return false;
      }
    }
    
    return true;
  });

  // Handle user click
  const handleUserClick = (userId) => {
    setUserModal({ isOpen: true, userId });
  };

  // Download CSV
  const downloadCSV = () => {
    const headers = ['Name', 'Email', 'Phone', 'Participation', 'Active Ticket', 'Total Tickets', 'Course Interest', 'First Seen', 'Last Active'];
    const rows = filteredUsers.map(user => {
      return [
        user.name || '-',
        user.email || '-',
        user.phone_number || '-',
        user.participation_level || '-',
        user.has_active_ticket ? 'Yes' : 'No',
        user.total_tickets || 0,
        (user.course_interests || []).join(', ') || '-',
        formatDate(user.first_seen),
        formatDate(user.last_interaction)
      ];
    });
    
    const csv = [headers, ...rows].map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `iron_lady_leads_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  };

  // Render different views
  const renderContent = () => {
    switch (activeView) {
      case 'tickets':
        return <TicketsView />;
      case 'feedbacks':
        return <FeedbacksView />;
      case 'courses':
        return <CourseInterestsView />;
      case 'broadcast':
        return <BroadcastStatusView />;
      default:
        return renderLeadsView();
    }
  };

  // Leads View
  const renderLeadsView = () => {
    if (loading) {
      return (
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading leads...</p>
        </div>
      );
    }

    if (error) {
      return (
        <div className="error-container">
          <p>❌ {error}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      );
    }

    return (
      <>
        <StatsCards users={filteredUsers} />

        <div className="table-header">
          <span className="lead-count">📊 Total Leads: <strong>{filteredUsers.length}</strong></span>
          <button className="btn btn-download" onClick={downloadCSV}>
            📥 Download CSV
          </button>
        </div>

        <div className="table-container">
          <table className="leads-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Participation</th>
                <th>Active Ticket</th>
                <th>Total Tickets</th>
                <th>Course Interest</th>
                <th>First Seen</th>
                <th>Last Active</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan="9" className="no-data">No leads found</td>
                </tr>
              ) : (
                filteredUsers.map(user => (
                  <tr key={user.id}>
                    <td>
                      <button 
                        className="name-link"
                        onClick={() => handleUserClick(user.id)}
                      >
                        {user.name || '-'}
                      </button>
                    </td>
                    <td>{user.email || '-'}</td>
                    <td className="phone-cell">
                      {user.phone_number ? (
                        <>
                          <a href={`tel:${user.phone_number}`} className="icon-btn" title="Call">📞</a>
                          <span>{user.phone_number}</span>
                          <a 
                            href={`https://wa.me/${user.phone_number}`} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="whatsapp-btn"
                            title="WhatsApp"
                          >
                            💬
                          </a>
                        </>
                      ) : '-'}
                    </td>
                    <td>
                      <span className={`badge ${
                        user.participation_level === 'Enrolled Participant' ? 'badge-success' :
                        user.participation_level === 'New to platform' ? 'badge-info' : 'badge-default'
                      }`}>
                        {user.participation_level === 'Enrolled Participant' ? 'Enrolled' :
                         user.participation_level === 'New to platform' ? 'New' :
                         user.participation_level || '-'}
                      </span>
                    </td>
                    <td>
                      {user.has_active_ticket ? (
                        <span className="badge badge-warning">🎫 Yes</span>
                      ) : (
                        <span className="dot">•</span>
                      )}
                    </td>
                    <td>{user.total_tickets || 0}</td>
                    <td>
                      {(user.course_interests || []).length > 0 ? (
                        <div className="course-tags">
                          {user.course_interests.map((course, idx) => (
                            <span key={idx} className="course-tag">{course}</span>
                          ))}
                        </div>
                      ) : '-'}
                    </td>
                    <td>{formatDate(user.first_seen)}</td>
                    <td>{formatDate(user.last_interaction)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </>
    );
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-content">
          <img src="/logo.png" alt="Iron Lady" className="logo" onError={(e) => e.target.style.display = 'none'} />
          <h1>Iron Lady - Wati Leads Dashboard</h1>
        </div>
        <div className="header-subtitle">ELEVATING A MILLION WOMEN TO THE TOP</div>
      </header>

      {/* Filters */}
      <div className="filters-section">
        <div className="filters-row">
          <div className="filter-group">
            <label>📅 Time Period</label>
            <select value={timeFilter} onChange={(e) => setTimeFilter(e.target.value)}>
              <option value="All">All Time</option>
              <option value="Today">Today</option>
              <option value="Last 2 Days">Last 2 Days</option>
              <option value="Last 3 Days">Last 3 Days</option>
              <option value="Last Week">Last Week</option>
              <option value="Last 2 Weeks">Last 2 Weeks</option>
              <option value="Last Month">Last Month</option>
            </select>
          </div>
          
          <div className="filter-group">
            <label>👤 Participation Level</label>
            <select value={participationFilter} onChange={(e) => setParticipationFilter(e.target.value)}>
              <option value="All">All</option>
              <option value="New to platform">New to Platform</option>
              <option value="Enrolled Participant">Enrolled Participant</option>
              <option value="Unknown">Unknown</option>
            </select>
          </div>
          
          <div className="filter-group search-group">
            <label>🔍 Search</label>
            <input
              type="text"
              placeholder="Search name, email, phone..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          
          <button className="btn btn-refresh" onClick={() => window.location.reload()}>
            🔄 Refresh
          </button>
        </div>
      </div>

      {/* Action Buttons */}
      <ActionButtons activeView={activeView} setActiveView={setActiveView} />

      {/* Main Content */}
      <main className="main-content">
        {renderContent()}
      </main>

      {/* Footer */}
      <footer className="footer">
        <p>Last updated: {new Date().toLocaleString('en-IN')} | Iron Lady WATI Analytics v5.0.0 - Ticket System</p>
      </footer>

      {/* Modals */}
      <UserDetailModal
        isOpen={userModal.isOpen}
        onClose={() => setUserModal({ isOpen: false, userId: null })}
        userId={userModal.userId}
      />
    </div>
  );
}

export default App;
