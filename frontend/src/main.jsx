import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { AlertCircle, BedDouble, CheckCircle2, ChevronRight, CircleDollarSign, ClipboardList, FileBarChart, Home, LogOut, Menu, MessageSquare, Plus, Search, Users, Wrench, X } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import './styles.css'

/* ------------------------------------------------------------------ API ---- */
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000', timeout: 30000 })
const clearSession = () => { localStorage.removeItem('hostel_token'); localStorage.removeItem('hostel_user') }
api.interceptors.request.use(config => {
  const token = localStorage.getItem('hostel_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use(r => r, error => {
  const isAuthCall = /\/auth\/(login|register)/.test(error.config?.url || '')
  if (error.response?.status === 401 && !isAuthCall) { clearSession(); window.location.assign('/login') }
  return Promise.reject(error)
})
const errorText = (error, fallback = 'Something went wrong. Please try again.') =>
  typeof error?.response?.data?.detail === 'string' ? error.response.data.detail
    : error?.request && !error?.response ? 'Cannot reach the API. Is the backend running?' : fallback
const inr = value => `₹${Number(value || 0).toLocaleString('en-IN')}`
const fmtDate = value => (value ? new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
const pretty = value => String(value ?? '').replaceAll('_', ' ')

const ROLE_NAV = {
  administrator: [
    { to: '/', label: 'Dashboard', icon: Home }, { to: '/residents', label: 'Residents', icon: Users },
    { to: '/rooms', label: 'Rooms & Beds', icon: BedDouble }, { to: '/allocations', label: 'Allocations', icon: ClipboardList },
    { to: '/complaints', label: 'Complaints', icon: MessageSquare }, { to: '/fees', label: 'Fees & Payments', icon: CircleDollarSign },
    { to: '/reports', label: 'Reports', icon: FileBarChart },
  ],
  resident: [
    { to: '/', label: 'My Dashboard', icon: Home }, { to: '/complaints', label: 'My Complaints', icon: MessageSquare },
    { to: '/fees', label: 'My Fees', icon: CircleDollarSign },
  ],
  maintenance_staff: [
    { to: '/', label: 'My Work', icon: Wrench }, { to: '/complaints', label: 'Complaint Queue', icon: MessageSquare },
  ],
}

/* ------------------------------------------------------------------ App ---- */
function App() {
  const [user, setUser] = useState(() => {
    if (!localStorage.getItem('hostel_token')) return null
    try { return JSON.parse(localStorage.getItem('hostel_user') || 'null') } catch { clearSession(); return null }
  })
  const logout = () => { clearSession(); setUser(null) }
  const authed = Boolean(user && localStorage.getItem('hostel_token'))
  return (
    <Routes>
      <Route path="/login" element={authed ? <Navigate to="/" replace /> : <Login onLogin={setUser} />} />
      <Route path="*" element={authed ? <Shell user={user} onLogout={logout} /> : <Navigate to="/login" replace />} />
    </Routes>
  )
}

function Login({ onLogin }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ full_name: '', email: '', password: '', roll_number: '', course: '', academic_year: '1', phone: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const registering = mode === 'register'
  const update = e => setForm({ ...form, [e.target.name]: e.target.value })
  const submit = async e => {
    e.preventDefault(); setLoading(true); setError('')
    try {
      const path = registering ? '/auth/register' : '/auth/login'
      const payload = registering ? { ...form, academic_year: Number(form.academic_year), phone: form.phone || null } : { email: form.email, password: form.password }
      const { data } = await api.post(path, payload)
      localStorage.setItem('hostel_token', data.access_token)
      localStorage.setItem('hostel_user', JSON.stringify(data.user))
      onLogin(data.user)
    } catch (err) {
      setError(err.response?.status === 401 ? 'Incorrect email or password.' : errorText(err, 'Request failed. Please try again.'))
    } finally { setLoading(false) }
  }
  return (
    <div className="login-page">
      <div className="login-decoration">
        <div className="brand-mark large">H</div><h1>HostelHub</h1><p>Simple, smarter hostel administration.</p>
        <div className="login-quote">“Everything you need to run a thriving residence, in one place.”</div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="brand-row"><div className="brand-mark">H</div><span>HostelHub</span></div>
        <h2>{registering ? 'Create your account' : 'Welcome back'}</h2>
        <p className="muted">{registering ? 'Register as a resident.' : 'Sign in to your workspace.'}</p>
        {error && <Notice text={error} />}
        {registering && <>
          <label>Full name<input name="full_name" value={form.full_name} onChange={update} required /></label>
          <label>Roll number<input name="roll_number" value={form.roll_number} onChange={update} required /></label>
          <label>Course<input name="course" value={form.course} onChange={update} required /></label>
          <label>Academic year<select name="academic_year" value={form.academic_year} onChange={update}>{[1, 2, 3, 4].map(y => <option key={y} value={y}>Year {y}</option>)}</select></label>
        </>}
        <label>Email address<input name="email" type="email" placeholder="you@example.com" value={form.email} onChange={update} required /></label>
        <label>Password<input name="password" type="password" placeholder="At least 8 characters" value={form.password} onChange={update} minLength="8" required /></label>
        <button className="button primary full" disabled={loading}>{loading ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}</button>
        <button type="button" className="text-button auth-switch" onClick={() => { setMode(registering ? 'login' : 'register'); setError('') }}>
          {registering ? 'Already have an account? Sign in' : 'New resident? Create an account'}
        </button>
      </form>
    </div>
  )
}

function Shell({ user, onLogout }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const items = ROLE_NAV[user.role] || ROLE_NAV.resident
  const title = items.find(item => item.to === location.pathname)?.label || 'Dashboard'
  const isAdmin = user.role === 'administrator'
  const isResident = user.role === 'resident'
  const initials = user.full_name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()
  const roleLabel = { administrator: 'Admin workspace', resident: 'Resident workspace', maintenance_staff: 'Maintenance workspace' }[user.role]
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="sidebar-top">
          <div className="brand-row"><div className="brand-mark">H</div><span>HostelHub</span></div>
          <button className="icon-button mobile-close" onClick={() => setMobileOpen(false)}><X size={20} /></button>
        </div>
        <div className="workspace-switch"><div className="avatar">{initials}</div><div><strong>{roleLabel}</strong><small>{pretty(user.role)}</small></div></div>
        <nav>{items.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} onClick={() => setMobileOpen(false)}><Icon size={18} /><span>{label}</span></NavLink>
        ))}</nav>
        <div className="sidebar-footer">
          <button className="logout-link" onClick={onLogout}><LogOut size={18} />Sign out</button>
          <div className="user-row"><div className="avatar green">{initials}</div><div><strong>{user.full_name}</strong><small>{user.email}</small></div></div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)}><Menu size={22} /></button>
          <div><div className="breadcrumb">Workspace <ChevronRight size={13} /> <strong>{title}</strong></div><h1>{title}</h1></div>
          <div className="topbar-actions"><div className="avatar green">{initials}</div></div>
        </header>
        <div className="page-content">
          <Routes>
            <Route path="/" element={<Dashboard user={user} />} />
            {isAdmin && <Route path="/residents" element={<DataPage type="residents" user={user} />} />}
            {isAdmin && <Route path="/rooms" element={<DataPage type="rooms" user={user} />} />}
            {isAdmin && <Route path="/allocations" element={<DataPage type="allocations" user={user} />} />}
            <Route path="/complaints" element={<DataPage type="complaints" user={user} />} />
            {(isAdmin || isResident) && <Route path="/fees" element={<DataPage type="fees" user={user} />} />}
            {isAdmin && <Route path="/reports" element={<Reports />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

/* ------------------------------------------------------------ Dashboards ---- */
function Dashboard({ user }) {
  if (user.role === 'administrator') return <AdminDashboard user={user} />
  if (user.role === 'resident') return <ResidentDashboard user={user} />
  return <StaffDashboard user={user} />
}

function Welcome({ user, children }) {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  return (
    <div>
      <p className="eyebrow">{new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).toUpperCase()}</p>
      <h2>{greeting}, {user.full_name.split(' ')[0]}</h2>
      <p className="muted">{children}</p>
    </div>
  )
}

function useLoad(loader, deps = []) {
  const [state, setState] = useState({ data: null, error: '', loading: true })
  useEffect(() => {
    let active = true
    setState(s => ({ ...s, loading: true }))
    loader().then(data => active && setState({ data, error: '', loading: false }))
      .catch(err => active && setState({ data: null, error: errorText(err, 'Could not load data.'), loading: false }))
    return () => { active = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return state
}

function AdminDashboard({ user }) {
  const navigate = useNavigate()
  const { data, error, loading } = useLoad(async () => {
    const [stats, activity, occupancy] = await Promise.all([api.get('/api/dashboard/stats'), api.get('/api/dashboard/activity'), api.get('/api/reports/occupancy')])
    return { stats: stats.data, activity: activity.data, occupancy: occupancy.data }
  })
  if (loading) return <LoadingState />
  if (error) return <Notice text={error} />
  const { stats, activity, occupancy } = data
  const cards = [
    { label: 'Total Residents', value: stats.total_residents, icon: Users, tone: 'teal' },
    { label: 'Room Occupancy', value: `${stats.occupancy_percent}%`, icon: BedDouble, tone: 'blue' },
    { label: 'Open Complaints', value: stats.open_complaints, icon: MessageSquare, tone: 'orange' },
    { label: 'Pending Fees', value: inr(stats.outstanding_balance), icon: CircleDollarSign, tone: 'purple' },
  ]
  const complaintData = [
    { name: 'Resolved', value: stats.resolved_complaints, color: '#0f766e' },
    { name: 'In progress', value: stats.in_progress_complaints, color: '#f59e0b' },
    { name: 'Open', value: Math.max(0, stats.open_complaints - stats.in_progress_complaints), color: '#cbd5e1' },
  ]
  return <>
    <div className="welcome-row">
      <Welcome user={user}>Here’s what’s happening across your hostels today.</Welcome>
      <button className="button primary" onClick={() => navigate('/allocations')}><Plus size={17} /> New allocation</button>
    </div>
    <div className="stats-grid">{cards.map(c => <StatCard key={c.label} {...c} />)}</div>
    <div className="dashboard-grid">
      <section className="panel">
        <PanelHeader title="Occupancy by hostel" />
        {occupancy.length ? (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={occupancy.map(o => ({ hostel: o.hostel, occupied: Number(o.occupied_beds), free: Number(o.available_beds) }))} margin={{ left: -20, right: 8, top: 12 }}>
              <CartesianGrid vertical={false} stroke="#eef2f3" />
              <XAxis dataKey="hostel" axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#94a3b8', fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="occupied" name="Occupied beds" fill="#0f766e" radius={[4, 4, 0, 0]} />
              <Bar dataKey="free" name="Free beds" fill="#cbd5e1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : <EmptyPage title="No hostels yet" icon={BedDouble} compact />}
      </section>
      <section className="panel">
        <PanelHeader title="Complaint status" />
        <div className="donut-wrap">
          <ResponsiveContainer width="100%" height={190}>
            <PieChart><Pie data={complaintData} dataKey="value" innerRadius={55} outerRadius={78} paddingAngle={3} stroke="none">{complaintData.map(i => <Cell key={i.name} fill={i.color} />)}</Pie><Tooltip /></PieChart>
          </ResponsiveContainer>
          <div className="donut-center"><strong>{stats.open_complaints}</strong><span>Open</span></div>
        </div>
        <div className="status-list">{complaintData.map(i => <div key={i.name}><span><i className="dot" style={{ background: i.color }} />{i.name}</span><strong>{i.value}</strong></div>)}</div>
      </section>
    </div>
    <div className="dashboard-grid lower">
      <section className="panel">
        <PanelHeader title="Recent activity" />
        {activity.length ? <div className="activity-list">{activity.map((item, i) => (
          <div className="activity-item" key={`${item.type}-${item.occurred_at}-${i}`}>
            <div className="activity-icon teal"><ClipboardList size={16} /></div>
            <div><strong>{item.title}</strong><p>{pretty(item.description)}</p><small>{new Date(item.occurred_at).toLocaleString('en-IN')}</small></div>
          </div>))}</div> : <p className="muted">No activity yet.</p>}
      </section>
      <section className="panel">
        <PanelHeader title="Quick actions" />
        <QuickActions actions={[['Add resident', Users, '/residents'], ['Assign a bed', BedDouble, '/allocations'], ['Record payment', CircleDollarSign, '/fees'], ['Review complaints', MessageSquare, '/complaints']]} />
      </section>
    </div>
  </>
}

function ResidentDashboard({ user }) {
  const navigate = useNavigate()
  const [refresh, setRefresh] = useState(0)
  const { data, error, loading } = useLoad(async () => {
    const [me, notes] = await Promise.all([api.get('/api/dashboard/me'), api.get('/api/notifications')])
    return { me: me.data, notes: notes.data }
  }, [refresh])
  if (loading) return <LoadingState />
  if (error) return <Notice text={error} />
  const { me, notes } = data
  const a = me.allocation
  const cards = [
    { label: 'My Room', value: a ? `${a.room_number} / ${a.bed_number}` : 'Not allocated', icon: BedDouble, tone: 'blue' },
    { label: 'Fees Due', value: inr(me.outstanding_balance), icon: CircleDollarSign, tone: 'purple' },
    { label: 'Open Complaints', value: me.open_complaints, icon: MessageSquare, tone: 'orange' },
    { label: 'Resolved', value: me.resolved_complaints, icon: CheckCircle2, tone: 'teal' },
  ]
  const markRead = async note => { if (note.is_read) return; try { await api.patch(`/api/notifications/${note.id}/read`); setRefresh(n => n + 1) } catch { /* ignore */ } }
  return <>
    <div className="welcome-row">
      <Welcome user={user}>{a ? `${a.hostel}, Room ${a.room_number}, Bed ${a.bed_number} · ${inr(a.monthly_amount)}/month · until ${fmtDate(a.end_date)}` : 'You have no bed allocated yet. The hostel office will assign one soon.'}</Welcome>
      <button className="button primary" onClick={() => navigate('/complaints')}><Plus size={17} /> Log complaint</button>
    </div>
    <div className="stats-grid">{cards.map(c => <StatCard key={c.label} {...c} />)}</div>
    <div className="dashboard-grid lower">
      <section className="panel">
        <PanelHeader title="My recent complaints" />
        {me.recent_complaints.length ? <div className="activity-list">{me.recent_complaints.map(c => (
          <div className="activity-item" key={c.id}>
            <div className="activity-icon orange"><MessageSquare size={16} /></div>
            <div style={{ flex: 1 }}><strong>{c.subject}</strong><p>{pretty(c.category)} · {c.priority} priority</p><small>{fmtDate(c.submitted_at)}</small></div>
            <span className={`badge ${badgeClass(c.status)}`}>{pretty(c.status)}</span>
          </div>))}</div> : <p className="muted">You haven’t filed any complaints.</p>}
      </section>
      <section className="panel">
        <PanelHeader title="Notifications" />
        {notes.length ? <div className="activity-list">{notes.slice(0, 6).map(n => (
          <div className="activity-item clickable" key={n.id} onClick={() => markRead(n)} title={n.is_read ? '' : 'Click to mark as read'}>
            <div className={`activity-icon ${n.is_read ? 'blue' : 'orange'}`}><AlertCircle size={16} /></div>
            <div><strong>{n.title}{!n.is_read && <span className="unread-dot" />}</strong><p>{n.message}</p><small>{new Date(n.created_at).toLocaleString('en-IN')}</small></div>
          </div>))}</div> : <p className="muted">No notifications.</p>}
        <div style={{ marginTop: 16 }}><QuickActions actions={[['Pay fees', CircleDollarSign, '/fees'], ['Log a complaint', MessageSquare, '/complaints']]} /></div>
      </section>
    </div>
  </>
}

function StaffDashboard({ user }) {
  const navigate = useNavigate()
  const { data, error, loading } = useLoad(async () => (await api.get('/api/dashboard/me')).data)
  if (loading) return <LoadingState />
  if (error) return <Notice text={error} />
  const cards = [
    { label: 'Assigned to me', value: data.assigned_to_me, icon: ClipboardList, tone: 'blue' },
    { label: 'In progress', value: data.in_progress, icon: Wrench, tone: 'orange' },
    { label: 'Waiting for someone', value: data.unassigned_open, icon: MessageSquare, tone: 'purple' },
    { label: 'Resolved by me', value: data.resolved_by_me, icon: CheckCircle2, tone: 'teal' },
  ]
  return <>
    <div className="welcome-row">
      <Welcome user={user}>Here’s your maintenance queue. Take a new job or keep your current ones moving.</Welcome>
      <button className="button primary" onClick={() => navigate('/complaints')}>Open complaint queue</button>
    </div>
    <div className="stats-grid">{cards.map(c => <StatCard key={c.label} {...c} />)}</div>
    <section className="panel">
      <PanelHeader title="Up next" />
      {data.queue.length ? <div className="activity-list">{data.queue.map(c => (
        <div className="activity-item" key={c.id}>
          <div className="activity-icon orange"><Wrench size={16} /></div>
          <div style={{ flex: 1 }}><strong>{c.subject}</strong><p>{c.resident_name} · {pretty(c.category)} · {c.priority} priority</p></div>
          <span className={`badge ${badgeClass(c.status)}`}>{pretty(c.status)}</span>
        </div>))}</div> : <p className="muted">Nothing in your queue. Nice.</p>}
    </section>
  </>
}

const QuickActions = ({ actions }) => {
  const navigate = useNavigate()
  return <div className="quick-actions">{actions.map(([label, Icon, path]) => (
    <button key={label} onClick={() => navigate(path)}><span className="quick-icon"><Icon size={18} /></span>{label}<ChevronRight size={16} /></button>))}</div>
}
function StatCard({ label, value, icon: Icon, tone }) {
  return <div className="stat-card"><div className={`stat-icon ${tone}`}><Icon size={20} /></div><div className="stat-copy"><span>{label}</span><strong>{value}</strong></div></div>
}
const PanelHeader = ({ title }) => <div className="panel-header"><h3>{title}</h3></div>

/* ------------------------------------------------------------- Data pages ---- */
const badgeClass = value => String(value).toLowerCase().replace(/[ _]/g, '-')

// Each page: how to load rows, which columns to show, and how a record becomes table cells.
const pages = {
  residents: {
    title: 'Residents', singular: 'resident', endpoint: '/api/residents', icon: Users,
    columns: ['Resident', 'Roll no.', 'Course', 'Current bed', 'Eligibility'],
    cells: r => [r.full_name, r.roll_number, `${r.course} (Y${r.academic_year})`, r.allocation || 'Unassigned', r.eligibility_status],
    statusCol: 4,
  },
  rooms: {
    title: 'Rooms & Beds', singular: 'room', endpoint: '/api/rooms', icon: BedDouble,
    columns: ['Room', 'Hostel', 'Type', 'Beds', 'Occupied', 'Monthly fee', 'Availability'],
    cells: r => [r.room_number, r.hostel, r.room_type, r.beds, `${r.occupied_beds} / ${r.beds}`, inr(r.monthly_amount), Number(r.available_beds) ? 'available' : 'full'],
    statusCol: 6, plainFirst: true,
  },
  allocations: {
    title: 'Allocations', singular: 'allocation', endpoint: '/api/allocations', icon: ClipboardList,
    columns: ['Resident', 'Hostel / Room / Bed', 'Start', 'End', 'Monthly fee', 'Status'],
    cells: r => [r.resident_name, `${r.hostel} / ${r.room_number} / ${r.bed_number}`, fmtDate(r.start_date), fmtDate(r.end_date), inr(r.monthly_amount), r.status],
    statusCol: 5,
  },
  complaints: {
    title: 'Complaints', singular: 'complaint', endpoint: '/api/complaints', icon: MessageSquare,
    columns: ['Issue', 'Resident', 'Category', 'Priority', 'Status', 'Assigned to'],
    cells: r => [r.subject, r.resident_name, pretty(r.category), r.priority, r.status, r.assigned_name || '—'],
    statusCol: 4, priorityCol: 3,
  },
  fees: {
    title: 'Fees & Payments', singular: 'payment', endpoint: '/api/invoices', icon: CircleDollarSign,
    columns: ['Resident', 'Invoice', 'Period', 'Amount', 'Outstanding', 'Due date', 'Status'],
    cells: r => [r.resident_name, `INV-${r.id}`, r.fee_period, inr(r.amount_due), inr(r.outstanding), fmtDate(r.due_date), r.status],
    statusCol: 6,
  },
}

function DataPage({ type, user }) {
  const config = pages[type]
  const isAdmin = user.role === 'administrator'
  const isResident = user.role === 'resident'
  const isStaff = user.role === 'maintenance_staff'
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [query, setQuery] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [transfer, setTransfer] = useState(null)
  const [staff, setStaff] = useState([])

  const load = async () => {
    try { const { data } = await api.get(config.endpoint); setRows(data); setError('') }
    catch (err) { setRows([]); setError(errorText(err, 'Could not load records.')) }
  }
  useEffect(() => { setLoading(true); setFormOpen(false); setTransfer(null); setSuccess(''); load().finally(() => setLoading(false)) }, [type]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (type === 'complaints' && isAdmin) api.get('/api/staff').then(r => setStaff(r.data)).catch(() => {}) }, [type, isAdmin])

  // Runs an API action, then refreshes the table and shows the outcome.
  const run = async (action, okMessage) => {
    setError(''); setSuccess('')
    try { const res = await action(); await load(); setSuccess(typeof okMessage === 'function' ? okMessage(res.data) : okMessage) }
    catch (err) { setError(errorText(err)) }
  }
  const confirmRun = (question, action, okMessage) => { if (window.confirm(question)) run(action, okMessage) }

  const filtered = useMemo(() => rows.filter(r => config.cells(r).join(' ').toLowerCase().includes(query.toLowerCase())), [rows, query, config])
  const canAdd = (isAdmin && type !== 'complaints') || (type === 'complaints' && !isStaff) || (isAdmin && type === 'complaints') || (isResident && type === 'fees')
  const addLabel = type === 'fees' ? 'Record payment' : `Add ${config.singular}`

  const actionsFor = row => {
    const buttons = []
    const btn = (label, onClick, key) => <button key={key || label} className="button secondary" onClick={onClick}>{label}</button>
    if (type === 'residents' && isAdmin) {
      if (row.eligibility_status !== 'eligible') buttons.push(btn('Mark eligible', () => run(() => api.patch(`/api/residents/${row.id}/eligibility`, { eligibility_status: 'eligible' }), 'Resident marked eligible.')))
      else buttons.push(btn('Mark ineligible', () => run(() => api.patch(`/api/residents/${row.id}/eligibility`, { eligibility_status: 'ineligible' }), 'Resident marked ineligible.')))
      buttons.push(btn('Remove', () => confirmRun(`Remove ${row.full_name}? Their bed is released and login disabled; fee history is kept.`, () => api.delete(`/api/residents/${row.id}`), 'Resident removed.')))
    }
    if (type === 'rooms' && isAdmin) buttons.push(btn('Delete', () => confirmRun(`Delete room ${row.room_number} and all its beds? This cannot be undone.`, () => api.delete(`/api/rooms/${row.id}`), 'Room deleted.')))
    if (type === 'allocations' && isAdmin && row.status === 'active') {
      buttons.push(btn('Transfer', () => { setTransfer(row); setFormOpen(false) }))
      buttons.push(btn('Cancel', () => confirmRun(`Cancel the allocation for ${row.resident_name}?`, () => api.delete(`/api/allocations/${row.id}`), 'Allocation cancelled.')))
    }
    if (type === 'complaints' && (isAdmin || isStaff)) {
      const step = to => run(() => api.patch(`/api/complaints/${row.id}`, { status: to }), `Complaint moved to ${pretty(to)}.`)
      const mine = isAdmin || row.assigned_to === user.id
      if (row.status === 'open') buttons.push(isAdmin ? <AssignControl key="assign" staff={staff} onAssign={staffId => run(() => api.patch(`/api/complaints/${row.id}`, { status: 'assigned', assigned_to: staffId }), 'Complaint assigned.')} /> : btn('Take this job', () => step('assigned')))
      if (row.status === 'assigned' && mine) buttons.push(btn('Start work', () => step('in_progress')))
      if (row.status === 'in_progress' && mine) buttons.push(btn('Mark resolved', () => { const remark = window.prompt('Resolution note (optional):') ; if (remark === null) return; run(() => api.patch(`/api/complaints/${row.id}`, { status: 'resolved', remark: remark || null }), 'Complaint resolved.') }))
      if (row.status === 'resolved' && mine) buttons.push(btn('Close', () => step('closed')))
      if (isAdmin) buttons.push(btn('Delete', () => confirmRun('Delete this complaint and its history?', () => api.delete(`/api/complaints/${row.id}`), 'Complaint deleted.')))
    }
    if (type === 'fees' && isAdmin) {
      const paid = ['paid', 'partially_paid'].includes(row.status) || Number(row.paid) > 0
      if (Number(row.outstanding) > 0) buttons.push(btn('Mark as paid', () => confirmRun('Mark this invoice as fully paid?', () => api.post(`/api/invoices/${row.id}/mark-paid`), 'Invoice marked as paid.')))
      if (paid) buttons.push(btn('Remove payments', () => confirmRun('Remove all payments for this invoice and set it back to unpaid?', () => api.post(`/api/invoices/${row.id}/remove-payment`), 'Payments removed.')))
      buttons.push(btn('Delete', () => confirmRun('Delete this invoice?', () => api.delete(`/api/invoices/${row.id}`), 'Invoice deleted.')))
    }
    return buttons
  }

  const intro = isResident && type === 'fees' ? 'View your invoices and pay what’s outstanding.'
    : isResident && type === 'complaints' ? 'Report a problem and follow it until it’s fixed.'
    : isStaff ? 'Take open jobs and move your assigned complaints forward.'
    : `Manage and monitor ${config.title.toLowerCase()} across all hostel buildings.`

  return <>
    <div className="page-intro">
      <div><p className="eyebrow">{type === 'complaints' ? 'TRACK & RESOLVE' : 'DIRECTORY'}</p><h2>{config.title}</h2><p className="muted">{intro}</p></div>
      <div className="row-actions">
        {isAdmin && type === 'allocations' && <button className="button secondary" onClick={() => confirmRun('Give every eligible, unallocated resident the next free bed?', () => api.post('/api/allocations/auto-assign'), d => `Auto-assigned ${d.assigned} resident(s)${d.waiting ? `; ${d.waiting} still waiting for a free bed` : ''}.`)}>Auto-assign waiting residents</button>}
        {isAdmin && type === 'fees' && <button className="button secondary" onClick={() => run(() => api.post('/api/invoices/generate'), d => `${d.created} new invoice(s) created for ${d.period}.`)}>Generate this month’s invoices</button>}
        {canAdd && <button className="button primary" onClick={() => { setFormOpen(true); setTransfer(null) }}><Plus size={17} /> {addLabel}</button>}
      </div>
    </div>
    {error && <Notice text={error} />}
    {success && <Notice text={success} type="success" />}
    {formOpen && <RecordForm type={type} user={user} onClose={() => setFormOpen(false)} onSaved={msg => { setFormOpen(false); setSuccess(msg); load() }} />}
    {transfer && <TransferForm allocation={transfer} onClose={() => setTransfer(null)} onSaved={() => { setTransfer(null); setSuccess('Resident transferred.'); load() }} />}
    <div className="toolbar"><div className="search-input"><Search size={17} /><input placeholder={`Search ${config.title.toLowerCase()}...`} value={query} onChange={e => setQuery(e.target.value)} /></div></div>
    <div className="panel table-panel">
      {loading ? <LoadingState /> : filtered.length ? (
        <div className="table-wrap"><table>
          <thead><tr>{config.columns.map(c => <th key={c}>{c}</th>)}<th>Actions</th></tr></thead>
          <tbody>{filtered.map(row => {
            const cells = config.cells(row); const actions = actionsFor(row)
            return <tr key={row.id}>
              {cells.map((cell, i) => <td key={i}>{
                i === 0 && !config.plainFirst ? <div className="person-cell"><div className="avatar small">{String(cell).split(' ').map(n => n[0]).join('').slice(0, 2)}</div><strong>{cell}</strong></div>
                  : i === config.statusCol || i === config.priorityCol ? <span className={`badge ${badgeClass(cell)}`}>{pretty(cell)}</span> : cell}</td>)}
              <td><div className="row-actions">{actions.length ? actions : <span className="muted">—</span>}</div></td>
            </tr>
          })}</tbody>
        </table></div>
      ) : <EmptyPage title={`No ${config.title.toLowerCase()} found`} icon={config.icon} compact />}
    </div>
  </>
}

function AssignControl({ staff, onAssign }) {
  const [staffId, setStaffId] = useState('')
  if (!staff.length) return <span className="muted">No maintenance staff</span>
  return <>
    <select className="mini-select" value={staffId} onChange={e => setStaffId(e.target.value)}><option value="">Assign to…</option>{staff.map(s => <option key={s.id} value={s.id}>{s.full_name}</option>)}</select>
    <button className="button secondary" disabled={!staffId} onClick={() => onAssign(Number(staffId))}>Assign</button>
  </>
}

function TransferForm({ allocation, onClose, onSaved }) {
  const [beds, setBeds] = useState([])
  const [form, setForm] = useState({ destination_bed_id: '', reason: '' })
  const [error, setError] = useState('')
  useEffect(() => { api.get('/api/beds').then(r => setBeds(r.data.filter(b => b.available_for_allocation))).catch(e => setError(errorText(e))) }, [])
  const submit = async e => {
    e.preventDefault(); setError('')
    try { await api.post(`/api/allocations/${allocation.id}/transfer`, { destination_bed_id: Number(form.destination_bed_id), reason: form.reason }); onSaved() }
    catch (err) { setError(errorText(err)) }
  }
  return <div className="panel form-panel">
    <div className="panel-header"><h3>Transfer {allocation.resident_name}</h3><button className="text-button" onClick={onClose}>Cancel</button></div>
    {error && <Notice text={error} />}
    <form className="record-form" onSubmit={submit}>
      <label>New bed<select value={form.destination_bed_id} onChange={e => setForm({ ...form, destination_bed_id: e.target.value })} required><option value="">Select a free bed</option>{beds.map(b => <option key={b.id} value={b.id}>{b.hostel} / {b.room_number} / {b.bed_number} · {inr(b.monthly_amount)}</option>)}</select></label>
      <label>Reason<input value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} required maxLength={500} /></label>
      <button className="button primary">Transfer resident</button>
    </form>
  </div>
}

function RecordForm({ type, user, onClose, onSaved }) {
  const isAdmin = user.role === 'administrator'
  const [form, setForm] = useState(type === 'rooms' ? { room_type: 'double', bed_count: 1 } : {})
  const [opts, setOpts] = useState({ residents: [], beds: [], hostels: [], invoices: [] })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const wanted = {
      allocations: { residents: '/api/residents', beds: '/api/beds' },
      rooms: { hostels: '/api/hostels' },
      complaints: isAdmin ? { residents: '/api/residents' } : {},
      fees: { invoices: '/api/invoices' },
    }[type] || {}
    Object.entries(wanted).forEach(([key, path]) => api.get(path).then(r => setOpts(o => ({ ...o, [key]: r.data }))).catch(e => setError(errorText(e, 'Could not load form options.'))))
  }, [type, isAdmin])

  const set = (name, value) => setForm(f => ({ ...f, [name]: value }))
  const field = (name, label, extra = {}) => <label>{label}<input name={name} value={form[name] ?? ''} onChange={e => set(name, e.target.value)} required {...extra} /></label>
  const select = (name, label, options, placeholder, extra = {}) => (
    <label>{label}<select name={name} value={form[name] ?? ''} onChange={e => set(name, e.target.value)} required {...extra}><option value="">{placeholder}</option>{options}</select></label>)

  const submit = async e => {
    e.preventDefault(); setSaving(true); setError('')
    try {
      const f = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== '' && v != null))
      let res, message
      if (type === 'residents') { res = await api.post('/api/residents', { ...f, academic_year: Number(f.academic_year) }); message = 'Resident added.' }
      if (type === 'rooms') {
        res = await api.post('/api/rooms', { ...f, hostel_id: Number(f.hostel_id), floor: Number(f.floor), bed_count: Number(f.bed_count || 1), monthly_amount: Number(f.monthly_amount), ...(f.bed_amount ? { bed_amount: Number(f.bed_amount) } : {}) })
        message = 'Room added.'
      }
      if (type === 'allocations') { res = await api.post('/api/allocations', { resident_id: Number(f.resident_id), bed_id: Number(f.bed_id), start_date: f.start_date }); message = 'Bed allocated.' }
      if (type === 'complaints') { res = await api.post('/api/complaints', { ...f, resident_id: isAdmin ? Number(f.resident_id) : user.resident_id, priority: f.priority || 'medium' }); message = 'Complaint submitted.' }
      if (type === 'fees') { res = await api.post(`/api/invoices/${f.invoice_id}/payments`, { amount: Number(f.amount), transaction_password: f.transaction_password }); message = `Payment recorded (${res.data.payment_reference}).` }
      onSaved(message)
    } catch (err) { setError(errorText(err, 'Could not save this record.')) } finally { setSaving(false) }
  }

  const payable = opts.invoices.filter(i => Number(i.outstanding) > 0)
  return <div className="panel form-panel">
    <div className="panel-header"><h3>{type === 'fees' ? 'Record fee payment' : `Add ${pages[type].singular}`}</h3><button className="text-button" onClick={onClose}>Cancel</button></div>
    {error && <Notice text={error} />}
    <form className="record-form" onSubmit={submit}>
      {type === 'residents' && <>{field('full_name', 'Full name')}{field('roll_number', 'Roll number')}{field('email', 'Email', { type: 'email' })}{field('course', 'Course')}{field('academic_year', 'Academic year', { type: 'number', min: 1, max: 8 })}{field('phone', 'Phone', { required: false })}</>}
      {type === 'rooms' && <>
        {select('hostel_id', 'Hostel', opts.hostels.map(h => <option key={h.id} value={h.id}>{h.name}</option>), 'Select hostel')}
        {field('room_number', 'Room number')}{field('floor', 'Floor', { type: 'number', min: 0 })}
        {select('room_type', 'Room type', ['single', 'double', 'triple', 'quad', 'other'].map(t => <option key={t}>{t}</option>), 'Select type')}
        {field('monthly_amount', 'Room monthly amount (₹)', { type: 'number', min: 0, step: '0.01' })}
        {field('bed_number', 'First bed label (A or 1)', { required: false })}
        {field('bed_count', 'Number of beds', { type: 'number', min: 1, max: 100 })}
        {field('bed_amount', 'Per-bed monthly amount (₹, defaults to room amount)', { type: 'number', min: 0, step: '0.01', required: false })}
      </>}
      {type === 'allocations' && <>
        {select('resident_id', 'Eligible resident', opts.residents.filter(r => r.eligibility_status === 'eligible' && !r.allocation_status).map(r => <option key={r.id} value={r.id}>{r.full_name} · {r.roll_number}</option>), 'Select resident')}
        {select('bed_id', 'Free bed', opts.beds.filter(b => b.available_for_allocation).map(b => <option key={b.id} value={b.id}>{b.hostel} / {b.room_number} / {b.bed_number} · {inr(b.monthly_amount)}</option>), 'Select bed')}
        {field('start_date', 'Start date', { type: 'date' })}
      </>}
      {type === 'complaints' && <>
        {isAdmin && select('resident_id', 'Resident', opts.residents.map(r => <option key={r.id} value={r.id}>{r.full_name}</option>), 'Select resident')}
        {select('category', 'Category', ['electrical', 'plumbing', 'cleaning', 'furniture', 'internet', 'security', 'other'].map(c => <option key={c} value={c}>{c}</option>), 'Select category')}
        {field('subject', 'Subject', { maxLength: 180 })}
        <label>Description<textarea name="description" rows={3} value={form.description ?? ''} onChange={e => set('description', e.target.value)} required /></label>
        <label>Priority<select name="priority" value={form.priority ?? 'medium'} onChange={e => set('priority', e.target.value)}>{['low', 'medium', 'high', 'urgent'].map(p => <option key={p}>{p}</option>)}</select></label>
        {!isAdmin && <p className="muted form-note">Your current room is attached automatically.</p>}
      </>}
      {type === 'fees' && <>
        <label>Invoice<select name="invoice_id" value={form.invoice_id ?? ''} required onChange={e => { const inv = payable.find(i => String(i.id) === e.target.value); setForm(f => ({ ...f, invoice_id: e.target.value, amount: inv ? inv.outstanding : '' })) }}>
          <option value="">Select invoice</option>{payable.map(i => <option key={i.id} value={i.id}>{isAdmin ? `${i.resident_name} · ` : ''}INV-{i.id} · {i.fee_period} · due {inr(i.outstanding)}</option>)}</select></label>
        {field('amount', 'Amount (₹)', { type: 'number', min: 0.01, step: '0.01' })}
        {field('transaction_password', 'Confirm with your account password', { type: 'password', autoComplete: 'current-password' })}
      </>}
      <button className="button primary" disabled={saving}>{saving ? 'Saving…' : type === 'fees' ? 'Confirm payment' : 'Save'}</button>
    </form>
  </div>
}

/* ---------------------------------------------------------------- Reports ---- */
function Reports() {
  const { data, error, loading } = useLoad(async () => {
    const [stats, occupancy] = await Promise.all([api.get('/api/dashboard/stats'), api.get('/api/reports/occupancy')])
    return { stats: stats.data, occupancy: occupancy.data }
  })
  if (loading) return <LoadingState />
  if (error) return <Notice text={error} />
  const { stats, occupancy } = data
  const totalComplaints = stats.open_complaints + stats.resolved_complaints
  const resolvedPct = totalComplaints ? Math.round(stats.resolved_complaints / totalComplaints * 100) : 0
  return <>
    <div className="page-intro"><div><p className="eyebrow">INSIGHTS</p><h2>Reports</h2><p className="muted">Live numbers from the database.</p></div></div>
    <div className="report-grid">
      <div className="panel report-card"><div className="report-number">{inr(stats.collected_this_month)}</div><span className="muted">Collected this month</span><p className="muted" style={{ marginTop: 12 }}>Still outstanding: <strong>{inr(stats.outstanding_balance)}</strong></p></div>
      <div className="panel report-card"><div className="report-number">{stats.occupancy_percent}%</div><span className="muted">Overall occupancy ({stats.occupied_beds} of {stats.beds} beds)</span><div className="progress"><span style={{ width: `${stats.occupancy_percent}%` }} /></div></div>
      <div className="panel report-card"><div className="report-number">{resolvedPct}%</div><span className="muted">Complaints resolved ({stats.resolved_complaints} of {totalComplaints})</span><div className="progress purple-progress"><span style={{ width: `${resolvedPct}%` }} /></div><small className="success-text">{stats.urgent_complaints} urgent still open</small></div>
    </div>
    <div className="panel"><PanelHeader title="Occupancy by hostel" />
      {occupancy.length ? <div className="report-bars">{occupancy.map(o => (
        <div key={o.hostel}><div><span>{o.hostel} · {o.occupied_beds}/{o.total_beds} beds</span><strong>{o.occupancy_percent}%</strong></div><div className="progress"><span style={{ width: `${o.occupancy_percent}%` }} /></div></div>))}</div> : <p className="muted">No hostels yet.</p>}
    </div>
  </>
}

/* ---------------------------------------------------------------- Shared ---- */
const LoadingState = () => <div className="state-box"><div className="spinner" /><strong>Loading…</strong><span className="muted">Fetching the latest data from the API.</span></div>
function EmptyPage({ title, icon: Icon = AlertCircle, compact = false }) {
  return <div className={`state-box ${compact ? 'compact' : ''}`}><div className="empty-icon"><Icon size={24} /></div><h3>{title}</h3><p className="muted">Nothing to show here yet.</p></div>
}
function Notice({ text, type = 'error' }) {
  const Icon = type === 'success' ? CheckCircle2 : AlertCircle
  return <div className={`notice ${type}`}><Icon size={17} /><span>{text}</span></div>
}

createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>)
