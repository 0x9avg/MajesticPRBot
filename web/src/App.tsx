import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import MainLayout from './components/MainLayout'
import ProtectedRoute from './components/ProtectedRoute'
import PermissionRoute from './components/rbac/PermissionRoute'
import MainHub from './pages/hub/MainHub'
import MediaList from './pages/media/MediaList'
import PRStats from './pages/stats/PRStats'
import SpectateLogs from './pages/action-logs/SpectateLogs'
import PunishmentReturns from './pages/returns/PunishmentReturns'
import CreateEvent from './pages/admin/components/CreateEvent'
import AdminPanel from './pages/admin/AdminPanel'
import BotDashboard from './pages/dashboard/BotDashboard'

import UserProfile from './pages/UserProfile'
import MediaProfile from './pages/MediaProfile'
import { ADMIN_SECTION_PERMISSIONS } from './rbac/catalog'

function App() {
    return (
        <Router>
            <Routes>
                <Route path="/login" element={<Login />} />

                <Route element={<ProtectedRoute />}>
                    <Route element={<MainLayout />}>
                        <Route path="/hub" element={<MainHub />} />
                        <Route path="/assistants/:id" element={<UserProfile />} />
                        <Route path="/media" element={<MediaList />} />
                        <Route path="/media/:id" element={<MediaProfile />} />
                        <Route path="/assistants" element={<PRStats />} />
                        <Route path="/logs" element={<SpectateLogs />} />
                        <Route
                            path="/returns"
                            element={
                                <PermissionRoute requireAny={['returns.view', 'returns.history.view']}>
                                    <PunishmentReturns />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/events/new"
                            element={
                                <PermissionRoute requireAny={['events.create']}>
                                    <CreateEvent />
                                </PermissionRoute>
                            }
                        />

                        <Route
                            path="/admin"
                            element={
                                <PermissionRoute requireAny={ADMIN_SECTION_PERMISSIONS}>
                                    <AdminPanel />
                                </PermissionRoute>
                            }
                        />

                        <Route
                            path="/bot"
                            element={
                                <PermissionRoute requireAny={['monitoring.view', 'monitoring.refresh']}>
                                    <BotDashboard />
                                </PermissionRoute>
                            }
                        />
                    </Route>
                </Route>

                <Route path="/" element={<Navigate to="/hub" replace />} />
                <Route path="*" element={<NotFound />} />
            </Routes>
        </Router>
    )
}

export default App
