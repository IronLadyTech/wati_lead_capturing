import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './App.css';

// API Base URL
const API_URL = 'http://localhost:8000';

// ============================================
// FLOATING MODAL COMPONENT
// ============================================
const QueryModal = ({ isOpen, onClose, data, onStatusChange }) => {
  if (!isOpen || !data) return null;

  const handleStatusToggle = () => {
    const newStatus = data.status === 'Resolved' ? 'Pending' : 'Resolved';
    onStatusChange(data.phone, newStatus);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>💬 User Query</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="modal-field">
            <span className="modal-label">👤 Name:</span>
            <span className="modal-value">{data.name || 'Unknown'}</span>
          </div>
          <div className="modal-field">
            <span className="modal-label">📱 Phone:</span>
            <span className="modal-value">{data.phone || '-'}</span>
          </div>
          <div className="modal-field">
            <span className="modal-label">📅 Date:</span>
            <span className="modal-value">{data.date || '-'}</span>
          </div>
          <div className="modal-field">
            <span className="modal-label">📊 Status:</span>
            <span className={`status-badge ${data.status === 'Resolved' ? 'status-resolved' : 'status-pending'}`}>
              {data.status || 'Pending'}
            </span>
          </div>
          <div className="modal-field">
            <span className="modal-label">💬 Query:</span>
            <div className="modal-message">{data.message || 'No query recorded'}</div>
          </div>
        </div>
        <div className="modal-footer">
          <button 
            className={`btn ${data.status === 'Resolved' ? 'btn-pending' : 'btn-resolve'}`}
            onClick={handleStatusToggle}
          >
            {data.status === 'Resolved' ? '🔄 Mark as Pending' : '✅ Mark as Resolved'}
          </button>
          <a href={`tel:${data.phone}`} className="btn btn-call">📞 Call</a>
          <a href={`https://wa.me/${data.phone}`} target="_blank" rel="noopener noreferrer" className="btn btn-whatsapp">💬 WhatsApp</a>
        </div>
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
                  <span className="detail-label">Total Interactions:</span>
                  <span className="detail-value">{user.interaction_count || 0}</span>
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
// STATS CARDS COMPONENT
// ============================================
const StatsCards = ({ users }) => {
  const totalLeads = users.length;
  const newUsers = users.filter(u => u.participation_level === 'New to platform').length;
  const enrolled = users.filter(u => u.participation_level === 'Enrolled Participant').length;
  const wantCounsellor = users.filter(u => u.has_call_request).length;

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
          <div className="stat-number">{wantCounsellor}</div>
          <div className="stat-label">Want Counsellor</div>
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
        className={`action-btn ${activeView === 'feedbacks' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'feedbacks' ? 'leads' : 'feedbacks')}
      >
        <span className="action-icon">💬</span>
        <span>View All Feedbacks</span>
      </button>
      <button 
        className={`action-btn ${activeView === 'courses' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'courses' ? 'leads' : 'courses')}
      >
        <span className="action-icon">📚</span>
        <span>View Course Interests</span>
      </button>
      <button 
        className={`action-btn ${activeView === 'broadcast' ? 'active' : ''}`}
        onClick={() => setActiveView(activeView === 'broadcast' ? 'leads' : 'broadcast')}
      >
        <span className="action-icon">📢</span>
        <span>View Broadcast Status</span>
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
    if (courseUsers[courseName]) return; // Already fetched
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

  // Prepare chart data
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

      {/* Tabs */}
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

      {/* Tab Content */}
      {activeTab === 'overview' ? (
        <div className="course-overview">
          <div className="course-overview-content">
            {/* Table */}
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

            {/* Chart */}
            <div className="course-chart-container">
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis 
                    dataKey="name" 
                    angle={-45} 
                    textAnchor="end" 
                    height={80}
                    interval={0}
                  />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="clicks" fill="#2196F3" name="Total Clicks" />
                </BarChart>
              </ResponsiveContainer>
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
  return (
    <div className="view-container">
      <div className="view-header">
        <h2>📢 Broadcast Status</h2>
      </div>
      <div className="coming-soon">
        <p>Broadcast tracking feature coming soon...</p>
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

// ============================================
// MAIN APP COMPONENT
// ============================================
function App() {
  // State
  const [users, setUsers] = useState([]);
  const [queries, setQueries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeView, setActiveView] = useState('leads');
  
  // Query Status Tracking (phone -> status)
  const [queryStatuses, setQueryStatuses] = useState({});
  
  // Filters
  const [timeFilter, setTimeFilter] = useState('All');
  const [participationFilter, setParticipationFilter] = useState('All');
  const [queryStatusFilter, setQueryStatusFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');
  
  // Modals
  const [queryModal, setQueryModal] = useState({ isOpen: false, data: null });
  const [userModal, setUserModal] = useState({ isOpen: false, userId: null });

  // Load query statuses from localStorage
  useEffect(() => {
    const savedStatuses = localStorage.getItem('queryStatuses');
    if (savedStatuses) {
      setQueryStatuses(JSON.parse(savedStatuses));
    }
  }, []);

  // Save query statuses to localStorage and update state
  const updateQueryStatus = (phone, status) => {
    const newStatuses = { ...queryStatuses, [phone]: status };
    setQueryStatuses(newStatuses);
    localStorage.setItem('queryStatuses', JSON.stringify(newStatuses));
    
    // Update modal data if open
    if (queryModal.isOpen && queryModal.data?.phone === phone) {
      setQueryModal({
        ...queryModal,
        data: { ...queryModal.data, status }
      });
    }
  };

  // Create query map (phone -> latest query)
  const queryMap = {};
  queries.forEach(q => {
    const phone = q.user_phone;
    if (phone) {
      if (!queryMap[phone] || new Date(q.created_at) > new Date(queryMap[phone].created_at)) {
        queryMap[phone] = q;
      }
    }
  });

  // Fetch data
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [usersRes, queriesRes] = await Promise.all([
          fetch(`${API_URL}/api/users`),
          fetch(`${API_URL}/api/queries`)
        ]);
        
        const usersData = await usersRes.json();
        const queriesData = await queriesRes.json();
        
        setUsers(usersData.users || []);
        setQueries(queriesData.queries || []);
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

    // Query Status filter
    if (queryStatusFilter !== 'All') {
      if (!user.has_call_request) return false; // No query = skip
      const status = queryStatuses[user.phone_number] || 'Pending';
      if (queryStatusFilter !== status) return false;
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

  // Handle query click
  const handleQueryClick = (user) => {
    const query = queryMap[user.phone_number];
    const status = queryStatuses[user.phone_number] || 'Pending';
    setQueryModal({
      isOpen: true,
      data: {
        name: user.name,
        phone: user.phone_number,
        date: query ? formatDate(query.created_at) : '-',
        message: query ? query.query_text : 'User requested counsellor but no specific query recorded.',
        status: status
      }
    });
  };

  // Handle user click
  const handleUserClick = (userId) => {
    setUserModal({ isOpen: true, userId });
  };

  // Get query status for styling
  const getQueryStatus = (phone) => {
    return queryStatuses[phone] || 'Pending';
  };

  // Download CSV
  const downloadCSV = () => {
    const headers = ['Name', 'Email', 'Phone', 'Participation', 'Counsellor', 'Query Status', 'Query', 'Course Interest', 'First Seen', 'Last Active'];
    const rows = filteredUsers.map(user => {
      const query = queryMap[user.phone_number];
      const status = queryStatuses[user.phone_number] || 'Pending';
      return [
        user.name || '-',
        user.email || '-',
        user.phone_number || '-',
        user.participation_level || '-',
        user.has_call_request ? 'Yes' : 'No',
        user.has_call_request ? status : '-',
        query ? query.query_text : '-',
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

  // Render different views based on activeView
  const renderContent = () => {
    switch (activeView) {
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

  // Leads View (main table)
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
        {/* Stats */}
        <StatsCards users={filteredUsers} />

        {/* Table Header */}
        <div className="table-header">
          <span className="lead-count">📊 Total Leads: <strong>{filteredUsers.length}</strong></span>
          <button className="btn btn-download" onClick={downloadCSV}>
            📥 Download CSV
          </button>
        </div>

        {/* Leads Table */}
        <div className="table-container">
          <table className="leads-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Participation</th>
                <th>Counsellor</th>
                <th>Query</th>
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
                filteredUsers.map(user => {
                  const queryStatus = getQueryStatus(user.phone_number);
                  const isResolved = queryStatus === 'Resolved';
                  
                  return (
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
                      <td>{user.has_call_request ? 'Yes' : 'No'}</td>
                      <td>
                        {user.has_call_request ? (
                          <button 
                            className={`query-btn ${isResolved ? 'query-resolved' : 'query-pending'}`}
                            onClick={() => handleQueryClick(user)}
                            title={`View Query (${queryStatus})`}
                          >
                            💬
                          </button>
                        ) : (
                          <span className="dot">•</span>
                        )}
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
                  );
                })
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
          <h1>Iron Lady - Leads Dashboard</h1>
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

          <div className="filter-group">
            <label>📊 Query Status</label>
            <select value={queryStatusFilter} onChange={(e) => setQueryStatusFilter(e.target.value)}>
              <option value="All">All</option>
              <option value="Pending">Pending</option>
              <option value="Resolved">Resolved</option>
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
        <p>Last updated: {new Date().toLocaleString('en-IN')} | Iron Lady WATI Analytics v4.1.0 - Broadcast Tracking</p>
      </footer>

      {/* Modals */}
      <QueryModal 
        isOpen={queryModal.isOpen}
        onClose={() => setQueryModal({ isOpen: false, data: null })}
        data={queryModal.data}
        onStatusChange={updateQueryStatus}
      />
      
      <UserDetailModal
        isOpen={userModal.isOpen}
        onClose={() => setUserModal({ isOpen: false, userId: null })}
        userId={userModal.userId}
      />
    </div>
  );
}

export default App;