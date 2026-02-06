import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import MainLayout from './components/MainLayout'
import ProtectedRoute from './components/ProtectedRoute'
import MainHub from './pages/hub/MainHub'
import MediaList from './pages/media/MediaList'
import PRStats from './pages/stats/PRStats'
import SpectateLogs from './pages/logs/SpectateLogs'
import CreateEvent from './pages/admin/components/CreateEvent'
import AdminPanel from './pages/admin/AdminPanel'
import BotDashboard from './pages/dashboard/BotDashboard'

import UserProfile from './pages/UserProfile'
import MediaProfile from './pages/MediaProfile'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<MainLayout />}>
            <Route path="/hub" element={<MainHub />} />
            <Route path="/profile" element={<UserProfile />} />
            <Route path="/profile/:id" element={<UserProfile />} />
            <Route path="/media" element={<MediaList />} />
            <Route path="/media/:id" element={<MediaProfile />} />
            <Route path="/pr-stats" element={<PRStats />} />
            <Route path="/logs" element={<SpectateLogs />} />
            <Route path="/events/new" element={<CreateEvent />} />

            <Route path="/admin" element={<AdminPanel />} />

            <Route path="/bot" element={<BotDashboard />} />
          </Route>
        </Route>

        <Route path="/" element={<Navigate to="/hub" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Router>
  )
}

export default App
