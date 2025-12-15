import React, { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense, memo } from 'react';

// API Base URL
const API_URL = "https://wati-leads-dashboard.iamironlady.com";

// ============================================
// API RESPONSE CACHE
// ============================================
const apiCache = new Map();
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

const getCachedResponse = (url) => {
  const cached = apiCache.get(url);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.data;
  }
  apiCache.delete(url);
  return null;
};

const setCachedResponse = (url, data) => {
  apiCache.set(url, { data, timestamp: Date.now() });
  // Clean old cache entries if cache gets too large
  if (apiCache.size > 100) {
    const now = Date.now();
    for (const [key, value] of apiCache.entries()) {
      if (now - value.timestamp > CACHE_TTL) {
        apiCache.delete(key);
      }
    }
  }
};

const fetchWithCache = async (url, options = {}) => {
  // Don't cache POST/PATCH/DELETE requests
  if (options.method && options.method !== 'GET') {
    return fetch(url, options);
  }
  
  const cached = getCachedResponse(url);
  if (cached) {
    return { ok: true, json: async () => cached, cached: true };
  }
  
  const response = await fetch(url, options);
  if (response.ok) {
    const data = await response.json();
    setCachedResponse(url, data);
    return { ...response, json: async () => data, cached: false };
  }
  
  return response;
};

// ============================================
// SIMPLE BAR CHART COMPONENT
// ============================================
const SimpleBarChart = memo(({ data }) => {
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
});

SimpleBarChart.displayName = 'SimpleBarChart';

// ============================================
// DEBOUNCE HOOK
// ============================================
const useDebounce = (value, delay) => {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
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
// COUNSELLOR QUERY TOOLTIP COMPONENT
// ============================================
const CounsellorQueryBadge = ({ query, requestedAt, userId, onMarkDone }) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const [marking, setMarking] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 });
  const iconRef = useRef(null);
  const tooltipRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        showTooltip &&
        iconRef.current &&
        !iconRef.current.contains(event.target) &&
        tooltipRef.current &&
        !tooltipRef.current.contains(event.target)
      ) {
        setShowTooltip(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showTooltip]);

  const handleClick = (e) => {
    e.stopPropagation();
    if (iconRef.current) {
      const rect = iconRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      
      let top = rect.top - 10;
      let transformY = '-100%';
      
      if (rect.top < 250) {
        top = rect.bottom + 10;
        transformY = '0';
      }
      
      let left = rect.left + rect.width / 2;
      if (left < 200) left = 200;
      if (left > viewportWidth - 200) left = viewportWidth - 200;
      
      setTooltipPosition({ top, left, transformY });
    }
    setShowTooltip(!showTooltip);
  };

  const handleMarkDone = async (e) => {
    e.stopPropagation();
    setMarking(true);
    try {
      const res = await fetch(`${API_URL}/api/users/${userId}/counsellor-done`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolved_by: 'Dashboard User' })
      });
      if (res.ok) {
        setShowTooltip(false);
        if (onMarkDone) onMarkDone();
      }
    } catch (err) {
      console.error(err);
    }
    setMarking(false);
  };

  if (!query) return <span className="dot">•</span>;

  return (
    <div className="counsellor-query-badge-container">
      <span 
        ref={iconRef}
        className="counsellor-query-icon" 
        onClick={handleClick}
        style={{ cursor: 'pointer' }}
      >
        📞💬
      </span>
      {showTooltip && (
        <div 
          ref={tooltipRef}
          className="counsellor-tooltip"
          style={{
            position: 'fixed',
            top: `${tooltipPosition.top}px`,
            left: `${tooltipPosition.left}px`,
            transform: `translate(-50%, ${tooltipPosition.transformY || '-100%'})`,
            zIndex: 9999
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="tooltip-header">
            <span>📞 Counsellor Request</span>
            {requestedAt && <span className="tooltip-date">{formatDate(requestedAt)}</span>}
          </div>
          <div className="tooltip-content">
            <p className="tooltip-query">{query}</p>
          </div>
          <div className="tooltip-actions">
            <button 
              className="btn btn-sm btn-resolve"
              onClick={handleMarkDone}
              disabled={marking}
            >
              {marking ? 'Processing...' : '✅ Mark Done'}
            </button>
            <button 
              className="btn btn-sm btn-secondary"
              onClick={() => setShowTooltip(false)}
              style={{ marginLeft: '8px' }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================
// TICKET DETAIL MODAL WITH CONVERSATION & REPLY-TO FEATURE
// ============================================
const TicketDetailModal = ({ isOpen, onClose, ticketId, onTicketUpdate }) => {
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [replyText, setReplyText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  
  // State for reply-to message feature
  const [replyToMessage, setReplyToMessage] = useState(null);
  
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const fetchTicketDetails = useCallback(async () => {
    if (!ticketId) return;
    
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/tickets/${ticketId}`);
      const data = await res.json();
      setTicket(data);
      setLoading(false);
      setTimeout(scrollToBottom, 100);
    } catch (err) {
      console.error(err);
      setError('Failed to load ticket details');
      setLoading(false);
    }
  }, [ticketId]);

  useEffect(() => {
    if (isOpen && ticketId) {
      fetchTicketDetails();
      setReplyToMessage(null);
    }
  }, [isOpen, ticketId, fetchTicketDetails]);

  // Handle clicking on a message to reply to it
  const handleSelectReplyTo = (msg) => {
    if (msg.direction === 'incoming' && msg.wati_message_id) {
      setReplyToMessage(msg);
    }
  };

  // Clear the reply-to selection
  const handleClearReplyTo = () => {
    setReplyToMessage(null);
  };

  const handleSendReply = async () => {
    if (!replyText.trim()) return;
    
    setSending(true);
    setError(null);
    
    try {
      const requestBody = {
        message: replyText,
        counsellor_name: 'Counsellor'
      };
      
      // Add reply-to information if a message is selected
      if (replyToMessage) {
        requestBody.reply_to_message_id = replyToMessage.id;
        requestBody.reply_to_wati_id = replyToMessage.wati_message_id;
      }
      
      const res = await fetch(`${API_URL}/api/tickets/${ticketId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      });
      
      const data = await res.json();
      
      if (res.ok && data.success) {
        setReplyText('');
        setReplyToMessage(null);
        fetchTicketDetails();
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
              <h3 className="conversation-title">
                💬 Conversation
                <span className="reply-hint">💡 Click on user message to reply to it specifically</span>
              </h3>
              <div className="messages-list">
                {ticket.messages.length === 0 ? (
                  <div className="no-messages">No messages yet</div>
                ) : (
                  ticket.messages.map((msg, idx) => (
                    <div 
                      key={idx} 
                      className={`message-bubble ${msg.direction === 'incoming' ? 'message-incoming' : 'message-outgoing'} ${msg.direction === 'incoming' && msg.wati_message_id ? 'message-replyable' : ''} ${replyToMessage?.id === msg.id ? 'message-selected' : ''}`}
                      onClick={() => handleSelectReplyTo(msg)}
                      title={msg.direction === 'incoming' && msg.wati_message_id ? 'Click to reply to this message' : ''}
                    >
                      {/* Show quoted message if this is a reply */}
                      {msg.reply_to_message && (
                        <div className="quoted-message">
                          <div className="quoted-message-header">
                            ↩️ Replying to {msg.reply_to_message.direction === 'incoming' ? 'User' : 'Counsellor'}
                          </div>
                          <div className="quoted-message-text">
                            {msg.reply_to_message.message_text?.substring(0, 100)}
                            {msg.reply_to_message.message_text?.length > 100 ? '...' : ''}
                          </div>
                        </div>
                      )}
                      
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
                      
                      {/* Reply button for incoming messages */}
                      {msg.direction === 'incoming' && msg.wati_message_id && (
                        <button 
                          className="reply-to-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSelectReplyTo(msg);
                          }}
                        >
                          ↩️ Reply
                        </button>
                      )}
                    </div>
                  ))
                )}
                <div ref={messagesEndRef} />
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
                    {/* Reply-To Preview */}
                    {replyToMessage && (
                      <div className="reply-to-preview">
                        <div className="reply-to-header">
                          <span>↩️ Replying to:</span>
                          <button 
                            className="reply-to-clear"
                            onClick={handleClearReplyTo}
                            title="Cancel reply"
                          >
                            ✕
                          </button>
                        </div>
                        <div className="reply-to-content">
                          <span className="reply-to-sender">👤 User</span>
                          <p className="reply-to-text">
                            {replyToMessage.message_text?.substring(0, 150)}
                            {replyToMessage.message_text?.length > 150 ? '...' : ''}
                          </p>
                        </div>
                      </div>
                    )}
                    
                    <textarea
                      className="reply-textarea"
                      placeholder={replyToMessage ? `Reply to: "${replyToMessage.message_text?.substring(0, 50)}..."` : "Type your reply here..."}
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
                        {sending ? '📤 Sending...' : replyToMessage ? '↩️ Send Reply' : '📤 Send Reply'}
                      </button>
                      <span className="reply-note">
                        {replyToMessage 
                          ? '↩️ Your reply will quote the selected message on WhatsApp'
                          : 'ℹ️ Click on a user message to reply to it specifically'
                        }
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
          setUser(data);
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
          ) : user?.user ? (
            <div className="user-details-grid">
              <div className="detail-card">
                <h3>📋 Basic Information</h3>
                <div className="detail-row">
                  <span className="detail-label">Name:</span>
                  <span className="detail-value">{user.user.name || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Email:</span>
                  <span className="detail-value">{user.user.email || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Phone:</span>
                  <span className="detail-value">{user.user.phone_number || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Participation:</span>
                  <span className="detail-value">{user.user.participation_level || '-'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Enrolled Program:</span>
                  <span className="detail-value">{user.user.enrolled_program || '-'}</span>
                </div>
              </div>
              <div className="detail-card">
                <h3>📊 Activity</h3>
                <div className="detail-row">
                  <span className="detail-label">First Seen:</span>
                  <span className="detail-value">{formatDate(user.user.first_seen)}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Last Active:</span>
                  <span className="detail-value">{formatDate(user.user.last_interaction)}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Active Ticket:</span>
                  <span className="detail-value">{user.user.has_active_ticket ? 'Yes' : 'No'}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Needs Counsellor:</span>
                  <span className="detail-value">{user.user.needs_counsellor ? 'Yes' : 'No'}</span>
                </div>
              </div>
              
              {user.user.counsellor_query && (
                <div className="detail-card detail-card-full">
                  <h3>📞 Counsellor Query</h3>
                  <div className="counsellor-query-detail">
                    <p>{user.user.counsellor_query}</p>
                    <span className="query-date">Requested: {formatDate(user.user.counsellor_requested_at)}</span>
                  </div>
                </div>
              )}
              
              {user.feedbacks && user.feedbacks.length > 0 && (
                <div className="detail-card detail-card-full">
                  <h3>💬 Feedbacks ({user.feedbacks.length})</h3>
                  <div className="feedbacks-mini-list">
                    {user.feedbacks.map((fb, idx) => (
                      <div key={idx} className="feedback-mini-item">
                        <p>{fb.feedback_text}</p>
                        <span className="feedback-mini-date">{formatDate(fb.created_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {user.tickets && user.tickets.length > 0 && (
                <div className="detail-card detail-card-full">
                  <h3>🎫 Tickets ({user.tickets.length})</h3>
                  <div className="tickets-mini-list">
                    {user.tickets.map((t, idx) => (
                      <div key={idx} className="ticket-mini-item">
                        <span className="ticket-mini-number">{t.ticket_number}</span>
                        <span className={`status-badge ${getStatusBadgeClass(t.status)}`}>
                          {t.status}
                        </span>
                        <span className="ticket-mini-date">{formatDate(t.created_at)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="error">User not found</div>
          )}
        </div>
        {user?.user && (
          <div className="modal-footer">
            <a href={`tel:${user.user.phone_number}`} className="btn btn-call">📞 Call</a>
            <a href={`https://wa.me/${user.user.phone_number}`} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp">💬 WhatsApp</a>
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================
// TICKETS VIEW COMPONENT
// ============================================
const TicketsView = () => {
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTicketId, setSelectedTicketId] = useState(null);
  const [skip, setSkip] = useState(0);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const limit = 50;
  
  const debouncedSearchTerm = useDebounce(searchTerm, 300);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    try {
      let url = `${API_URL}/api/tickets?limit=${limit}&skip=${skip}`;
      
      if (statusFilter !== 'all') {
        url += `&status=${statusFilter}`;
      }
      if (activeTab === 'queries') {
        url += '&category=query';
      } else if (activeTab === 'concerns') {
        url += '&category=concern';
      }
      
      const res = await fetchWithCache(url);
      const data = await res.json();
      setTickets(data.tickets || []);
      setStats(data.stats || {});
      setTotal(data.total || 0);
      setHasMore(data.has_more || false);
      setLoading(false);
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  }, [activeTab, statusFilter, skip, limit]);

  useEffect(() => {
    setSkip(0); // Reset to first page when filters change
  }, [activeTab, statusFilter]);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  const filteredTickets = tickets.filter(t => {
    if (!debouncedSearchTerm) return true;
    const search = debouncedSearchTerm.toLowerCase();
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
            <span className="ticket-stat-number">{stats.queries || 0}</span>
            <span className="ticket-stat-label">Queries</span>
          </div>
          <div className="ticket-stat ticket-stat-concerns">
            <span className="ticket-stat-number">{stats.concerns || 0}</span>
            <span className="ticket-stat-label">Concerns</span>
          </div>
        </div>
      )}

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
        <button className="btn btn-refresh" onClick={() => { setSkip(0); fetchTickets(); }}>
          🔄 Refresh
        </button>
      </div>

      {loading && skip === 0 ? (
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

      {/* Pagination Controls */}
      {!loading && tickets.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px', marginTop: '20px', padding: '20px' }}>
          <button 
            className="btn btn-secondary" 
            onClick={() => setSkip(Math.max(0, skip - limit))}
            disabled={skip === 0}
          >
            ← Previous
          </button>
          <span style={{ padding: '0 15px' }}>
            Showing {skip + 1} - {Math.min(skip + limit, total)} of {total}
          </span>
          <button 
            className="btn btn-secondary" 
            onClick={() => setSkip(skip + limit)}
            disabled={!hasMore}
          >
            Next →
          </button>
        </div>
      )}

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
const StatsCards = memo(({ users }) => {
  const totalLeads = users.length;
  const newUsers = users.filter(u => u.participation_level === 'New to platform').length;
  const enrolled = users.filter(u => u.participation_level === 'Enrolled Participant').length;
  const needsCounsellor = users.filter(u => u.needs_counsellor).length;

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
        <div className="stat-icon">📞</div>
        <div className="stat-content">
          <div className="stat-number">{needsCounsellor}</div>
          <div className="stat-label">Need Counsellor</div>
        </div>
      </div>
    </div>
  );
});

StatsCards.displayName = 'StatsCards';

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
      const res = await fetchWithCache(`${API_URL}/api/course-interests`);
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
      const res = await fetchWithCache(`${API_URL}/api/course-interests/${courseName}`);
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
      const res = await fetchWithCache(`${API_URL}/api/feedbacks`);
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
        <button className="btn btn-refresh" onClick={fetchFeedbacks}>🔄 Refresh</button>
      </div>

      <div className="feedbacks-list">
        {feedbacks.length === 0 ? (
          <div className="no-data-card">
            <p>No feedbacks recorded yet</p>
            <small>Feedbacks are captured when users click "Provide feedback" and send their message.</small>
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
        fetchWithCache(`${API_URL}/api/broadcasts/stats`),
        fetchWithCache(`${API_URL}/api/broadcasts/failed`)
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
  
  const [timeFilter, setTimeFilter] = useState('All');
  const [participationFilter, setParticipationFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  const [skip, setSkip] = useState(0);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const limit = 50;
  
  const debouncedSearchTerm = useDebounce(searchTerm, 300);
  
  const [userModal, setUserModal] = useState({ isOpen: false, userId: null });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/users?limit=${limit}&skip=${skip}`);
      const data = await res.json();
      setUsers(data.users || []);
      setTotal(data.total || 0);
      setHasMore(data.has_more || false);
      setError(null);
    } catch (err) {
      setError('Failed to fetch data. Make sure backend is running.');
      console.error(err);
    }
    setLoading(false);
  }, [skip, limit]);

  useEffect(() => {
    setSkip(0); // Reset to first page when filters change
  }, [timeFilter, participationFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const filteredUsers = useMemo(() => {
    return users.filter(user => {
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
      
      if (participationFilter !== 'All' && user.participation_level !== participationFilter) {
        return false;
      }
      
      if (debouncedSearchTerm) {
        const search = debouncedSearchTerm.toLowerCase();
        const name = (user.name || '').toLowerCase();
        const email = (user.email || '').toLowerCase();
        const phone = (user.phone_number || '').toLowerCase();
        if (!name.includes(search) && !email.includes(search) && !phone.includes(search)) {
          return false;
        }
      }
      
      return true;
    });
  }, [users, timeFilter, participationFilter, debouncedSearchTerm]);

  const handleUserClick = (userId) => {
    setUserModal({ isOpen: true, userId });
  };

  const downloadCSV = () => {
    const headers = ['Name', 'Email', 'Phone', 'Participation', 'Needs Counsellor', 'Counsellor Query', 'Course Interest', 'First Seen', 'Last Active'];
    const rows = filteredUsers.map(user => {
      return [
        user.name || '-',
        user.email || '-',
        user.phone_number || '-',
        user.participation_level || '-',
        user.needs_counsellor ? 'Yes' : 'No',
        user.counsellor_query || '-',
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
                <th>Need Counsellor</th>
                <th>Course Interest</th>
                <th>First Seen</th>
                <th>Last Active</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan="8" className="no-data">No leads found</td>
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
                      <CounsellorQueryBadge 
                        query={user.counsellor_query}
                        requestedAt={user.counsellor_requested_at}
                        userId={user.id}
                        onMarkDone={fetchData}
                      />
                    </td>
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
        
        {/* Pagination Controls */}
        {!loading && users.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px', marginTop: '20px', padding: '20px' }}>
            <button 
              className="btn btn-secondary" 
              onClick={() => setSkip(Math.max(0, skip - limit))}
              disabled={skip === 0}
            >
              ← Previous
            </button>
            <span style={{ padding: '0 15px' }}>
              Showing {skip + 1} - {Math.min(skip + limit, total)} of {total}
            </span>
            <button 
              className="btn btn-secondary" 
              onClick={() => setSkip(skip + limit)}
              disabled={!hasMore}
            >
              Next →
            </button>
          </div>
        )}
      </>
    );
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <img src="/logo.png" alt="Iron Lady" className="logo" onError={(e) => e.target.style.display = 'none'} />
          <h1>Iron Lady - Wati Leads Dashboard</h1>
        </div>
        <div className="header-subtitle">ELEVATING A MILLION WOMEN TO THE TOP</div>
      </header>

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
          
          <button className="btn btn-refresh" onClick={() => { setSkip(0); fetchData(); }}>
            🔄 Refresh
          </button>
        </div>
      </div>

      <ActionButtons activeView={activeView} setActiveView={setActiveView} />

      <main className="main-content">
        {renderContent()}
      </main>

      <footer className="footer">
        <p>Last updated: {new Date().toLocaleString('en-IN')} | Iron Lady WATI Analytics v5.2.0 - Reply-to-Message Feature</p>
      </footer>

      <UserDetailModal
        isOpen={userModal.isOpen}
        onClose={() => setUserModal({ isOpen: false, userId: null })}
        userId={userModal.userId}
      />
    </div>
  );
}

export default App;
