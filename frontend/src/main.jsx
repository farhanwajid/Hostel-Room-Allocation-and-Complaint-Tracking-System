import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { jsPDF } from 'jspdf'
import { AlertCircle, ArrowDownRight, ArrowUpRight, BedDouble, ChevronRight, CircleDollarSign, ClipboardList, FileBarChart, Home, LogOut, Menu, MessageSquare, MoreHorizontal, Plus, Search, Settings, Users, X } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import './styles.css'

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000', timeout: 5000 })
api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401) {
    localStorage.removeItem('hostel_token')
    localStorage.removeItem('hostel_user')
    window.location.assign('/login')
  }
  return Promise.reject(error)
})
api.interceptors.request.use(config => { const token = localStorage.getItem('hostel_token'); if (token) config.headers.Authorization = `Bearer ${token}`; return config })
const navItems = [
  { to: '/', label: 'Dashboard', icon: Home }, { to: '/residents', label: 'Residents', icon: Users },
  { to: '/rooms', label: 'Rooms & Beds', icon: BedDouble }, { to: '/allocations', label: 'Allocations', icon: ClipboardList },
  { to: '/complaints', label: 'Complaints', icon: MessageSquare }, { to: '/fees', label: 'Fees & Payments', icon: CircleDollarSign },
  { to: '/reports', label: 'Reports', icon: FileBarChart },
]
const dashboardData = {
  stats: [
    { label: 'Total Residents', value: '1,248', delta: '+8.2%', icon: Users, tone: 'teal' }, { label: 'Room Occupancy', value: '87.4%', delta: '+3.1%', icon: BedDouble, tone: 'blue' },
    { label: 'Open Complaints', value: '24', delta: '-12.5%', icon: MessageSquare, tone: 'orange' }, { label: 'Pending Fees', value: '₹18,420', delta: '+4.6%', icon: CircleDollarSign, tone: 'purple' },
  ],
  occupancy: [{ month: 'Jan', occupied: 82, capacity: 100 }, { month: 'Feb', occupied: 84, capacity: 100 }, { month: 'Mar', occupied: 81, capacity: 100 }, { month: 'Apr', occupied: 86, capacity: 100 }, { month: 'May', occupied: 87, capacity: 100 }, { month: 'Jun', occupied: 87, capacity: 100 }, { month: 'Jul', occupied: 90, capacity: 100 }, { month: 'Aug', occupied: 87, capacity: 100 }],
  complaints: [{ name: 'Resolved', value: 64, color: '#0f766e' }, { name: 'In progress', value: 24, color: '#f59e0b' }, { name: 'New', value: 12, color: '#e2e8f0' }],
}
async function getResource(path, fallback) { try { const { data } = await api.get(path); return { data: Array.isArray(data) ? data : data?.items || data, error: null } } catch (error) { return { data: fallback, error: error?.response?.data?.detail || 'The API is unavailable. Showing demo data instead.' } } }
function App() {
  const [user, setUser] = useState(() => {
    const token = localStorage.getItem('hostel_token')
    if (!token || token === 'demo-session') return null
    try { return JSON.parse(localStorage.getItem('hostel_user') || 'null') } catch { localStorage.removeItem('hostel_user'); return null }
  })
  useEffect(() => { if (localStorage.getItem('hostel_token') === 'demo-session') { localStorage.removeItem('hostel_token'); localStorage.removeItem('hostel_user') } }, [])
  const logout = () => { localStorage.removeItem('hostel_token'); localStorage.removeItem('hostel_user'); setUser(null) }
  const authed = Boolean(localStorage.getItem('hostel_token') && user)
  return <Routes><Route path="/login" element={authed ? <Navigate to="/" replace /> : <Login onLogin={setUser} />} /><Route path="*" element={authed ? <Shell user={user} onLogout={logout} /> : <Navigate to="/login" replace />} /></Routes>
}
function Login({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ full_name: '', email: '', password: '', roll_number: '', course: '', academic_year: '1', phone: '' })
  const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const isRegistering = mode === 'register'
  const update = event => setForm({ ...form, [event.target.name]: event.target.value })
  const submit = async event => { event.preventDefault(); setLoading(true); setError(''); try { const path = isRegistering ? '/auth/register' : '/auth/login'; const payload = isRegistering ? { ...form, academic_year: Number(form.academic_year) } : { email: form.email, password: form.password }; const { data } = await api.post(path, payload); localStorage.setItem('hostel_token', data.access_token); localStorage.setItem('hostel_user', JSON.stringify(data.user)); onLogin(data.user) } catch (error) { setError(error.response?.status === 401 ? 'Incorrect email or password. Please try again.' : error.response?.data?.detail || (error.request ? 'Cannot connect to the API. Make sure the backend is running.' : 'Request failed. Please try again.')) } finally { setLoading(false) } }
  return <div className="login-page"><div className="login-decoration"><div className="brand-mark large">H</div><h1>HostelHub</h1><p>Simple, smarter hostel administration.</p><div className="login-quote">“Everything you need to run a thriving residence, in one place.”</div></div><form className="login-card" onSubmit={submit}><div className="brand-row"><div className="brand-mark">H</div><span>HostelHub</span></div><h2>Welcome to HostelHub</h2><p className="muted">{isRegistering ? 'Create an account to get started.' : 'Sign in to your workspace.'}</p>{error && <div className="notice">{error}</div>}{isRegistering && <><label>Full name<input name="full_name" value={form.full_name} onChange={update} required /></label><label>Roll number<input name="roll_number" value={form.roll_number} onChange={update} required /></label><label>Course<input name="course" value={form.course} onChange={update} required /></label><label>Academic year<select name="academic_year" value={form.academic_year} onChange={update}><option value="1">Year 1</option><option value="2">Year 2</option><option value="3">Year 3</option><option value="4">Year 4</option></select></label></>}<label>Email address<input name="email" type="email" placeholder="you@example.com" value={form.email} onChange={update} required /></label><label>Password<input name="password" type="password" placeholder="Enter your password" value={form.password} onChange={update} minLength="8" required /></label><button className="button primary full" disabled={loading}>{loading ? 'Please wait…' : isRegistering ? 'Create account' : 'Sign in'}</button><button type="button" className="text-button auth-switch" onClick={() => { setMode(isRegistering ? 'login' : 'register'); setError('') }}>{isRegistering ? 'Already have an account? Sign in' : 'New user? Create an account'}</button></form></div>
}
function Shell({ user, onLogout }) {
  const [mobileOpen, setMobileOpen] = useState(false); const location = useLocation(); const title = navItems.find(item => item.to === location.pathname)?.label || 'Dashboard'
  const role = user.role; const isAdmin = role === 'administrator'; const isMaintenance = role === 'maintenance_staff'
  const visibleItems = isAdmin ? navItems : navItems.filter(item => ['/', '/complaints', '/fees'].includes(item.to) && !(isMaintenance && item.to === '/fees'))
  const initials = user.full_name.split(' ').map(part => part[0]).join('').slice(0, 2).toUpperCase()
  return <div className="app-shell"><aside className={`sidebar ${mobileOpen ? 'open' : ''}`}><div className="sidebar-top"><div className="brand-row"><div className="brand-mark">H</div><span>HostelHub</span></div><button className="icon-button mobile-close" onClick={() => setMobileOpen(false)}><X size={20} /></button></div><div className="workspace-switch"><div className="avatar">{initials}</div><div><strong>{isAdmin ? 'Admin workspace' : 'Resident workspace'}</strong><small>Central campus</small></div><ChevronRight size={15} /></div><nav>{visibleItems.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} onClick={() => setMobileOpen(false)}><Icon size={18} /><span>{label}</span></NavLink>)}</nav><div className="sidebar-footer"><button className="logout-link" onClick={onLogout}><LogOut size={18} />Sign out</button><div className="user-row"><div className="avatar green">{initials}</div><div><strong>{user.full_name}</strong><small>{role.replace('_', ' ')}</small></div><MoreHorizontal size={17} /></div></div></aside><main className="main-content"><header className="topbar"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)}><Menu size={22} /></button><div><div className="breadcrumb">Workspace <ChevronRight size={13} /> <strong>{title}</strong></div><h1>{title}</h1></div><div className="topbar-actions"><div className="avatar green">{initials}</div></div></header><div className="page-content"><Routes><Route path="/" element={<Dashboard user={user} />} /><Route path="/residents" element={isAdmin ? <DataPage type="residents" user={user} /> : <EmptyPage title="Resident profile" icon={Users} />} /><Route path="/rooms" element={isAdmin ? <DataPage type="rooms" user={user} /> : <Navigate to="/" replace />} /><Route path="/allocations" element={isAdmin ? <DataPage type="allocations" user={user} /> : <Navigate to="/" replace />} /><Route path="/complaints" element={<DataPage type="complaints" user={user} />} /><Route path="/fees" element={<DataPage type="fees" user={user} />} /><Route path="/reports" element={isAdmin ? <Reports /> : <Navigate to="/" replace />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></div></main></div>
}
function Dashboard({ user }) {
  const navigate = useNavigate()
  const isAdmin = user.role === 'administrator'
  const [stats, setStats] = useState(null)
  const [activity, setActivity] = useState([])

  useEffect(() => {
    if (!isAdmin) return
    Promise.all([api.get('/api/dashboard/stats'), api.get('/api/dashboard/activity')])
      .then(([statsResponse, activityResponse]) => {
        setStats(statsResponse.data)
        setActivity(activityResponse.data)
      })
      .catch(() => {})
  }, [isAdmin])

  const adminStats = stats ? [
    { label: 'Total Residents', value: stats.total_residents, icon: Users, tone: 'teal' },
    { label: 'Room Occupancy', value: `${stats.occupancy_percent}%`, icon: BedDouble, tone: 'blue' },
    { label: 'Open Complaints', value: stats.open_complaints, icon: MessageSquare, tone: 'orange' },
    { label: 'Pending Fees', value: `₹${Number(stats.outstanding_balance || 0).toLocaleString('en-IN')}`, icon: CircleDollarSign, tone: 'purple' },
  ] : []

  const actions = isAdmin
    ? [['Add resident', Users, '/residents'], ['Assign a bed', BedDouble, '/allocations'], ['Record payment', CircleDollarSign, '/fees'], ['Log complaint', MessageSquare, '/complaints']]
    : [['Submit complaint', MessageSquare, '/complaints'], ['View fee payments', CircleDollarSign, '/fees']]

  return <>
    <div className="welcome-row">
      <div>
        <p className="eyebrow">{isAdmin ? 'ADMINISTRATOR DASHBOARD' : 'RESIDENT DASHBOARD'}</p>
        <h2>Good morning, {user.full_name.split(' ')[0]} <span>👋</span></h2>
        <p className="muted">{isAdmin ? 'Manage your hostel operations from one place.' : 'View your complaints and fee payments from one place.'}</p>
      </div>
      <button className="button primary" onClick={() => navigate(isAdmin ? '/allocations' : '/complaints')}>
        <Plus size={17} /> {isAdmin ? 'New allocation' : 'New complaint'}
      </button>
    </div>
    {isAdmin && <div className="stats-grid">{adminStats.map(stat => <StatCard key={stat.label} {...stat} />)}</div>}
    <div className={`dashboard-grid lower ${isAdmin ? '' : 'resident-dashboard'}`}>
      {isAdmin && <section className="panel"><PanelHeader title="Recent activity" />{activity.length ? <div className="activity-list">{activity.map(item => <div className="activity-item" key={`${item.type}-${item.occurred_at}`}><div className="activity-icon teal"><ClipboardList size={16} /></div><div><strong>{item.title}</strong><p>{item.description}</p><small>{new Date(item.occurred_at).toLocaleString()}</small></div></div>)}</div> : <Activity />}</section>}
      <section className="panel"><PanelHeader title={isAdmin ? 'Quick actions' : 'Your hostel actions'} /><div className="quick-actions">{actions.map(([label, Icon, path]) => <button key={label} onClick={() => navigate(path)}><span className="quick-icon"><Icon size={18} /></span>{label}<ChevronRight size={16} /></button>)}</div></section>
    </div>
  </>
}
function StatCard({ label, value, delta, icon: Icon, tone }) { return <div className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={20} /></div><div className="stat-copy"><span>{label}</span><strong>{value}</strong>{delta ? <small className={delta.startsWith('-') ? 'down' : ''}>{delta.startsWith('-') ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />} {delta} <em>vs last month</em></small> : <small>&nbsp;</small>}</div></div> }
function PanelHeader({ title }) { return <div className="panel-header"><h3>{title}</h3></div> }
function Activity() { return <div className="activity-list">{[['New allocation approved', 'Rahul Mehta was assigned to Room 203, Bed B', '12 min ago', BedDouble, 'teal'], ['Complaint status updated', 'Water leakage in Block A marked as in progress', '48 min ago', MessageSquare, 'orange'], ['Payment received', 'Nadia Ali paid the October accommodation fee', '2 hrs ago', CircleDollarSign, 'purple'], ['New resident added', 'Samuel Okoro joined Central campus', '4 hrs ago', Users, 'blue']].map(([title, description, time, Icon, tone]) => <div className="activity-item" key={title}><div className={`activity-icon ${tone}`}><Icon size={16} /></div><div><strong>{title}</strong><p>{description}</p><small>{time}</small></div></div>)}</div> }
const pageConfig = {
  residents: { title: 'Residents', singular: 'resident', endpoint: '/residents', icon: Users, columns: ['Resident', 'Student ID', 'Room', 'Status'], rows: [['Nadia Ali', 'ST-2024-001', 'B-203 / Bed A', 'Active'], ['Samuel Okoro', 'ST-2024-002', 'A-108 / Bed B', 'Active'], ['Emma Wilson', 'ST-2023-118', 'C-014 / Bed A', 'Active'], ['Daniel Kim', 'ST-2023-094', 'B-107 / Bed C', 'Pending']] },
  rooms: { title: 'Rooms & Beds', singular: 'room', endpoint: '/rooms', icon: BedDouble, columns: ['Room', 'Hostel', 'Type', 'Capacity', 'Occupancy', 'Monthly fee', 'Status'], rows: [['A-108', 'Maple Hall', 'Double', '2 beds', '2 / 2', '₹420', 'Full'], ['B-203', 'Cedar House', 'Triple', '3 beds', '2 / 3', '₹420', 'Available'], ['C-014', 'Oak Residence', 'Single', '1 bed', '1 / 1', '₹420', 'Full'], ['B-107', 'Cedar House', 'Triple', '3 beds', '1 / 3', '₹420', 'Available']] },
  allocations: { title: 'Allocations', singular: 'allocation', endpoint: '/allocations', icon: ClipboardList, columns: ['Resident', 'Room / Bed', 'Start date', 'End date', 'Monthly fee', 'Status'], rows: [['Nadia Ali', 'B-203 / A', 'Oct 12, 2026', 'Jun 30, 2027', '₹420', 'Active'], ['Samuel Okoro', 'A-108 / B', 'Oct 10, 2026', 'Jun 30, 2027', '₹420', 'Active'], ['Emma Wilson', 'C-014 / A', 'Sep 28, 2026', 'Jun 30, 2027', '₹420', 'Active'], ['Daniel Kim', 'B-107 / C', 'Sep 21, 2026', 'Jun 30, 2027', '₹420', 'Pending']] },
  complaints: { title: 'Complaints', singular: 'complaint', endpoint: '/complaints', icon: MessageSquare, columns: ['Issue', 'Resident', 'Category', 'Priority', 'Status'], rows: [['Water leakage in Block A', 'Rahul Mehta', 'Maintenance', 'High', 'In progress'], ['Slow Wi-Fi in study room', 'Amina Yusuf', 'Facilities', 'Medium', 'New'], ['Room key replacement', 'Jon Bell', 'Access', 'Low', 'Resolved'], ['No hot water - Floor 2', 'Maria Chen', 'Maintenance', 'High', 'New']] },
  fees: { title: 'Fees & Payments', singular: 'payment', endpoint: '/fees', icon: CircleDollarSign, columns: ['Resident', 'Invoice', 'Period', 'Amount', 'Due date', 'Status'], rows: [['Nadia Ali', 'INV-1028', 'October 2026', '₹420.00', 'Oct 05, 2026', 'Paid'], ['Samuel Okoro', 'INV-1027', 'October 2026', '₹420.00', 'Oct 05, 2026', 'Paid'], ['Emma Wilson', 'INV-0982', 'October 2026', '₹420.00', 'Oct 05, 2026', 'Pending'], ['Daniel Kim', 'INV-0978', 'October 2026', '₹420.00', 'Oct 05, 2026', 'Overdue']] },
}
function DataPage({ type, user }) { const config = pageConfig[type]; const [rows, setRows] = useState(config.rows); const [loading, setLoading] = useState(true); const [apiError, setApiError] = useState(''); const [query, setQuery] = useState(''); const [formOpen, setFormOpen] = useState(false); const refresh = () => getResource(config.endpoint, config.rows).then(result => { if (result.error) setApiError(result.error); if (Array.isArray(result.data)) setRows(result.data.map(item => Array.isArray(item) ? item : mapApiRow(type, item))); }); const remove = async id => { if (!window.confirm(`Remove this ${config.singular}? This cannot be undone.`)) return; const paths = { residents: `/api/residents/${id}`, allocations: `/api/allocations/${id}`, rooms: `/api/rooms/${id}`, complaints: `/api/complaints/${id}`, fees: `/api/invoices/${id}` }; try { await api.delete(paths[type]); await refresh() } catch (error) { setApiError(error.response?.data?.detail || 'This record could not be removed.') } }; const markPaid = async id => { if (!window.confirm('Mark this invoice as fully paid?')) return; try { await api.post(`/api/invoices/${id}/mark-paid`); await refresh() } catch (error) { setApiError(error.response?.data?.detail || 'Invoice could not be marked as paid.') } }; const removePayment = async id => { if (!window.confirm('Remove all payment records for this invoice and return it to unpaid?')) return; try { await api.post(`/api/invoices/${id}/remove-payment`); await refresh() } catch (error) { setApiError(error.response?.data?.detail || 'Payment status could not be removed.') } }; useEffect(() => { let active = true; getResource(config.endpoint, config.rows).then(result => { if (!active) return; if (result.error) setApiError(result.error); if (Array.isArray(result.data)) setRows(result.data.map(item => Array.isArray(item) ? item : mapApiRow(type, item))); }).finally(() => active && setLoading(false)); return () => { active = false } }, [config.endpoint, type]); const filtered = useMemo(() => rows.filter(row => row.join(' ').toLowerCase().includes(query.toLowerCase())), [rows, query]); const canAdd = user.role === 'administrator' || type === 'complaints' || type === 'fees'; const canDelete = user.role === 'administrator' && ['residents', 'allocations', 'rooms', 'complaints', 'fees'].includes(type); const canMarkPaid = user.role === 'administrator' && type === 'fees'; return <><div className="page-intro"><div><p className="eyebrow">{config.title === 'Complaints' ? 'TRACK & RESOLVE' : 'DIRECTORY'}</p><h2>{config.title}</h2><p className="muted">{user.role === 'resident' && type === 'fees' ? 'View your invoices and pay outstanding fees securely.' : `Manage and monitor ${config.title.toLowerCase()} across all hostel buildings.`}</p></div>{canAdd && <button className="button primary" onClick={() => setFormOpen(true)}><Plus size={17} /> {user.role === 'resident' && type === 'fees' ? 'Pay fee' : `Add ${config.singular}`}</button>}</div>{apiError && <Notice type="info" text={apiError} />}{formOpen && <RecordForm type={type} user={user} onClose={() => setFormOpen(false)} onSaved={() => { setFormOpen(false); refresh() }} />}<div className="toolbar"><div className="search-input"><Search size={17} /><input placeholder={`Search ${config.title.toLowerCase()}...`} value={query} onChange={e => setQuery(e.target.value)} /></div></div><div className="panel table-panel">{loading ? <LoadingState /> : filtered.length ? <Table columns={config.columns} rows={filtered} type={type} onDelete={canDelete ? remove : null} onMarkPaid={canMarkPaid ? markPaid : null} onRemovePayment={canMarkPaid ? removePayment : null} /> : <EmptyPage title={`No ${config.title.toLowerCase()} found`} icon={config.icon} compact />}</div></> }
function RecordForm({ type, user, onClose, onSaved }) {
  const [form, setForm] = useState({}); const [options, setOptions] = useState({ residents: [], beds: [], hostels: [], invoices: [] }); const [error, setError] = useState(''); const [saving, setSaving] = useState(false)
  useEffect(() => { if (!['allocations', 'complaints', 'fees', 'rooms'].includes(type)) return; Promise.allSettled([api.get('/residents'), api.get('/beds'), api.get('/api/hostels'), api.get('/fees')]).then(results => { const [residents, beds, hostels, invoices] = results; setOptions({ residents: residents.status === 'fulfilled' ? residents.value.data || [] : [], beds: beds.status === 'fulfilled' ? beds.value.data || [] : [], hostels: hostels.status === 'fulfilled' ? hostels.value.data || [] : [], invoices: invoices.status === 'fulfilled' ? invoices.value.data || [] : [] }); const failed = results.some(result => result.status === 'rejected'); if (failed) setError('Some form options could not be loaded. Refresh and try again.') }) }, [type])
  const field = (name, label, extra = {}) => <label>{label}<input name={name} value={form[name] || ''} onChange={e => setForm({ ...form, [name]: e.target.value })} required {...extra} /></label>
  const submit = async event => { event.preventDefault(); setSaving(true); setError(''); try {
    let path; let payload = { ...form }
    if (type === 'residents') { path = '/api/residents'; payload.academic_year = Number(payload.academic_year) }
    if (type === 'rooms') { path = '/api/rooms'; payload.hostel_id = Number(payload.hostel_id); payload.floor = Number(payload.floor); payload.bed_count = Number(payload.bed_count) }
    if (type === 'allocations') { path = '/api/allocations'; payload.resident_id = Number(payload.resident_id); payload.bed_id = Number(payload.bed_id) }
    if (type === 'complaints') { path = '/api/complaints'; payload.resident_id = user.role === 'resident' ? user.resident_id : Number(payload.resident_id); if (payload.room_id) payload.room_id = Number(payload.room_id); if (payload.bed_id) payload.bed_id = Number(payload.bed_id) }
    if (type === 'fees') { const invoice = options.invoices.find(item => String(item.id) === String(payload.invoice_id)); path = `/api/invoices/${payload.invoice_id}/payments`; payload = { amount: Number(payload.amount), transaction_password: payload.transaction_password }; if (!invoice) throw new Error('Select an invoice') }
    await api.post(path, payload); onSaved()
  } catch (err) { setError(err.response?.status === 401 ? 'Your session has expired or you do not have administrator permission. Please sign in again.' : err.response?.data?.detail || err.message || 'Could not save this record.') } finally { setSaving(false) } }
  return <div className="panel form-panel"><div className="panel-header"><h3>{type === 'fees' ? 'Record fee payment' : `Add ${pageConfig[type].singular}`}</h3><button className="text-button" onClick={onClose}>Cancel</button></div>{error && <Notice text={error} /> }<form className="record-form" onSubmit={submit}>
    {type === 'residents' && <>{field('full_name', 'Full name')}{field('roll_number', 'Roll number')}{field('email', 'Email', { type: 'email' })}{field('course', 'Course')}{field('academic_year', 'Academic year', { type: 'number', min: 1, max: 8 })}{field('phone', 'Phone')}</>}
    {type === 'rooms' && <>{<label>Hostel<select name="hostel_id" value={form.hostel_id || ''} onChange={e => setForm({ ...form, hostel_id: e.target.value })} required><option value="">Select hostel</option>{options.hostels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}{field('room_number', 'Room number')}{field('floor', 'Floor', { type: 'number', min: 0 })}{field('room_type', 'Room type')}{field('monthly_amount', 'Room monthly amount (₹)', { type: 'number', min: 0, step: '0.01' })}{field('bed_number', 'First bed number')}{field('bed_count', 'Number of beds', { type: 'number', min: 1, max: 100 })}{field('bed_amount', 'Monthly amount per bed (₹)', { type: 'number', min: 0, step: '0.01' })}</>}
    {type === 'allocations' && <><label>Resident<select name="resident_id" value={form.resident_id || ''} onChange={e => setForm({ ...form, resident_id: e.target.value })} required><option value="">Select resident</option>{options.residents.filter(item => ['eligible', 'pending'].includes(item.eligibility_status) && !item.allocation_status).map(item => <option key={item.id} value={item.id}>{item.full_name} · {item.roll_number}</option>)}</select></label><label>Available bed<select name="bed_id" value={form.bed_id || ''} onChange={e => setForm({ ...form, bed_id: e.target.value })} required><option value="">Select bed</option>{options.beds.filter(item => item.available_for_allocation === 1 || item.available_for_allocation === true || (item.status === 'available' && !item.resident_id)).map(item => <option key={item.id} value={item.id}>{item.hostel} / {item.room_number} / {item.bed_number} · ₹{item.monthly_amount || 0}</option>)}</select></label>{field('start_date', 'Start date', { type: 'date' })}</>}
    {type === 'complaints' && <>{user.role === 'administrator' && <label>Resident<select name="resident_id" value={form.resident_id || ''} onChange={e => setForm({ ...form, resident_id: e.target.value })} required><option value="">Select resident</option>{options.residents.map(item => <option key={item.id} value={item.id}>{item.full_name}</option>)}</select></label>}<label>Category<select name="category" value={form.category || ''} onChange={e => setForm({ ...form, category: e.target.value })} required><option value="">Select category</option><option value="electrical">Electrical</option><option value="plumbing">Plumbing</option><option value="cleaning">Cleaning</option><option value="furniture">Furniture</option><option value="internet">Internet</option><option value="security">Security</option><option value="other">Other</option></select></label>{field('subject', 'Subject')}{field('description', 'Description')}{<label>Priority<select name="priority" value={form.priority || 'medium'} onChange={e => setForm({ ...form, priority: e.target.value })}><option>low</option><option>medium</option><option>high</option><option>urgent</option></select></label>}</>}
    {type === 'fees' && <><label>Invoice<select name="invoice_id" value={form.invoice_id || ''} onChange={e => setForm({ ...form, invoice_id: e.target.value })} required><option value="">Select invoice</option>{options.invoices.filter(item => Number(item.outstanding) > 0).map(item => <option key={item.id} value={item.id}>INV-{item.id} · {item.fee_period} · outstanding {item.outstanding}</option>)}</select></label>{field('amount', 'Amount', { type: 'number', min: 0.01, step: '0.01' })}{field('transaction_password', 'Transaction password', { type: 'password' })}</>}
    <button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save to database'}</button>
  </form></div>
}
function mapApiRow(type, item) {
  const withId = values => Object.assign(values, { recordId: item.id })
  if (type === 'residents') return withId([item.full_name, item.roll_number, item.allocation_status || 'Unassigned', item.eligibility_status]);
  if (type === 'rooms') return withId([item.room_number, item.hostel, item.room_type, `${item.beds || 0} beds`, `${item.occupied_beds || 0} / ${item.beds || 0}`, `₹${item.monthly_amount || 0}`, Number(item.available_beds || 0) ? 'Available' : 'Full']);
  if (type === 'allocations') return withId([item.resident_name, `${item.room_number || '—'} / ${item.bed_number || '—'}`, item.start_date, item.end_date || '—', `₹${item.monthly_amount || 0}`, item.status]);
  if (type === 'complaints') return withId([item.subject, item.resident_name, item.category, item.priority, item.status]);
  if (type === 'fees') return withId([item.resident_name, `INV-${item.id}`, item.fee_period, item.amount_due, item.due_date, item.status]);
  return Object.values(item);
}
function Table({ columns, rows, type, onDelete, onMarkPaid, onRemovePayment }) { return <div className="table-wrap"><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}<th>Actions</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row[0]}-${index}`}>{row.map((cell, i) => <td key={`${cell}-${i}`}>{i === 0 && type !== 'rooms' ? <div className="person-cell"><div className="avatar small">{String(cell).split(' ').map(n => n[0]).join('').slice(0, 2)}</div><strong>{cell}</strong></div> : <StatusCell value={cell} column={columns[i]} />}</td>)}<td className="row-actions">{onMarkPaid && row.recordId && !['paid', 'partially_paid'].includes(String(row[5]).toLowerCase()) && <button className="button secondary" onClick={() => onMarkPaid(row.recordId)}>Mark as paid</button>}{onRemovePayment && row.recordId && ['paid', 'partially_paid'].includes(String(row[5]).toLowerCase()) && <button className="button secondary" onClick={() => onRemovePayment(row.recordId)}>Remove payment</button>}{onDelete && row.recordId ? <button className="icon-button" title="Delete record" onClick={() => onDelete(row.recordId)}><X size={17} /></button> : !onMarkPaid && !onRemovePayment && <button className="icon-button"><MoreHorizontal size={17} /></button>}</td></tr>)}</tbody></table></div> }
function StatusCell({ value, column }) { return ['Status', 'Priority'].includes(column) ? <span className={`badge ${value.toLowerCase().replaceAll(' ', '-')}`}>{value}</span> : value }
function Reports() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.get('/api/reports/summary')
      .then(response => setReport(response.data))
      .catch(err => setError(err.response?.data?.detail || 'Report data could not be loaded.'))
  }, [])

  const money = value => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  const downloadPdf = () => {
    if (!report) return
    const pdf = new jsPDF()
    let y = 18
    pdf.setFontSize(18)
    pdf.text('Hostel Management Summary Report', 14, y)
    y += 8
    pdf.setFontSize(10)
    pdf.setTextColor(90)
    pdf.text(`Generated: ${new Date().toLocaleString()}`, 14, y)
    y += 12
    pdf.setTextColor(30)
    pdf.setFontSize(12)
    pdf.text('Overall summary', 14, y)
    y += 8
    pdf.setFontSize(10)
    ;[
      `Residents: ${report.residents}`,
      `Rooms: ${report.rooms}`,
      `Beds: ${report.beds}`,
      `Occupied beds: ${report.occupied_beds}`,
      `Available beds: ${report.available_beds}`,
      `Occupancy: ${report.occupancy_percent}%`,
      `Open complaints: ${report.open_complaints}`,
      `Resolved complaints: ${report.resolved_complaints}`,
      `Urgent complaints: ${report.urgent_complaints}`,
      `Invoices: ${report.invoices}`,
      `Paid amount: ${money(report.paid_amount)}`,
      `Outstanding fees: ${money(report.outstanding_balance)}`,
    ].forEach(line => { pdf.text(line, 18, y); y += 6 })
    y += 6
    pdf.setFontSize(12)
    pdf.text('Occupancy by hostel', 14, y)
    y += 8
    pdf.setFontSize(10)
    report.hostels.forEach(hostel => {
      if (y > 275) { pdf.addPage(); y = 18 }
      pdf.text(`${hostel.hostel}: ${hostel.occupied_beds}/${hostel.total_beds} occupied (${hostel.occupancy_percent}%), ${hostel.available_beds} available`, 18, y)
      y += 6
    })
    pdf.save(`hostel-summary-${new Date().toISOString().slice(0, 10)}.pdf`)
  }

  if (error) return <><div className="page-intro"><div><p className="eyebrow">INSIGHTS</p><h2>Reports</h2></div></div><Notice text={error} /></>
  if (!report) return <LoadingState />
  const cards = [
    ['Total residents', report.residents, Users, 'teal'],
    ['Rooms and beds', `${report.rooms} / ${report.beds}`, BedDouble, 'blue'],
    ['Occupancy', `${report.occupancy_percent}%`, BedDouble, 'orange'],
    ['Outstanding fees', money(report.outstanding_balance), CircleDollarSign, 'purple'],
  ]
  return <><div className="page-intro"><div><p className="eyebrow">INSIGHTS</p><h2>Reports</h2><p className="muted">A complete summary of hostel residents, rooms, complaints, occupancy, and payments.</p></div><button className="button primary" onClick={downloadPdf}><FileBarChart size={17} /> Download PDF</button></div><div className="stats-grid">{cards.map(([label, value, Icon, tone]) => <StatCard key={label} label={label} value={value} icon={Icon} tone={tone} />)}</div><div className="report-summary-grid"><section className="panel"><PanelHeader title="Operations summary" /><div className="summary-list"><div><span>Occupied beds</span><strong>{report.occupied_beds}</strong></div><div><span>Available beds</span><strong>{report.available_beds}</strong></div><div><span>Open complaints</span><strong>{report.open_complaints}</strong></div><div><span>In-progress complaints</span><strong>{report.in_progress_complaints}</strong></div><div><span>Resolved complaints</span><strong>{report.resolved_complaints}</strong></div><div><span>Urgent complaints</span><strong>{report.urgent_complaints}</strong></div></div></section><section className="panel"><PanelHeader title="Payment summary" /><div className="summary-list"><div><span>Total invoices</span><strong>{report.invoices}</strong></div><div><span>Paid amount</span><strong>{money(report.paid_amount)}</strong></div><div><span>Outstanding fees</span><strong>{money(report.outstanding_balance)}</strong></div></div></section></div><section className="panel"><PanelHeader title="Occupancy by hostel" /><div className="report-bars">{report.hostels.length ? report.hostels.map(hostel => <div key={hostel.hostel}><div><span>{hostel.hostel}</span><strong>{hostel.occupancy_percent}% ({hostel.occupied_beds}/{hostel.total_beds})</strong></div><div className="progress"><span style={{ width: `${Math.min(100, hostel.occupancy_percent)}%` }} /></div><small className="muted">{hostel.available_beds} beds available</small></div>) : <p className="muted">No hostel occupancy data available.</p>}</div></section></>
}
function LoadingState() { return <div className="state-box"><div className="spinner" /><strong>Loading records…</strong><span className="muted">Fetching the latest data from the API.</span></div> }
function EmptyPage({ title, icon: Icon = AlertCircle, compact = false }) { return <div className={`state-box ${compact ? 'compact' : 'large-state'}`}><div className="empty-icon"><Icon size={24} /></div><h3>{title}</h3><p className="muted">There’s nothing to show here yet. Connect your API or add your first record.</p></div> }
function Notice({ text, type = 'error' }) { return <div className={`notice ${type}`}><AlertCircle size={17} /><span>{text}</span></div> }
createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>)
