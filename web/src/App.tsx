import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import MainLayout from './components/MainLayout'
import ProtectedRoute from './components/ProtectedRoute'
import {
  MainHub,
  MediaList,
  PRStats,
  SpectateLogs,
  CreateEvent,
  AdminPanel,
  BotDashboard
} from './pages/Placeholders'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<MainLayout />}>
            <Route path="/hub" element={<MainHub />} />
            <Route path="/media" element={<MediaList />} />
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
