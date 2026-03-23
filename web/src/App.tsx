import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate, matchPath, useLocation, useNavigate } from 'react-router-dom'
import Login from './pages/Login'
import MaintenancePage from './pages/MaintenancePage'
import NotFound from './pages/NotFound'
import MainLayout from './components/MainLayout'
import ProtectedRoute from './components/ProtectedRoute'
import PermissionRoute from './components/rbac/PermissionRoute'
import MainHub from './pages/hub/MainHub'
import MediaList from './pages/media/MediaList'
import PRStats from './pages/stats/PRStats'
import AssistantWeeklyStatsPage from './pages/stats/AssistantWeeklyStatsPage'
import SpectateLogs from './pages/action-logs/SpectateLogs'
import PunishmentReturns from './pages/returns/PunishmentReturns'
import ComplaintsPage from './pages/complaints/ComplaintsPage'
import PunishmentRemovals from './pages/removals/PunishmentRemovals'
import AdminPanel from './pages/admin/AdminPanel'
import BotDashboard from './pages/dashboard/BotDashboard'

import UserProfile from './pages/UserProfile'
import MediaProfile from './pages/MediaProfile'
import { ADMIN_SECTION_PERMISSIONS } from './rbac/catalog'
import { onSiteMaintenance } from './api/client'
import { APP_TITLE, formatDocumentTitle } from './utils/documentTitle'

const routeTitles = [
    { path: '/login', title: 'Вход' },
    { path: '/maintenance', title: 'Технические работы' },
    { path: '/hub', title: 'Хаб' },
    { path: '/assistants/weekly/manage', title: 'Недельная статистика' },
    { path: '/assistants/:id', title: 'Ассистенты' },
    { path: '/assistants', title: 'Ассистенты' },
    { path: '/media/:id', title: 'Медиа' },
    { path: '/media', title: 'Медиа' },
    { path: '/logs', title: 'Логи' },
    { path: '/returns', title: 'Возвраты' },
    { path: '/complaints', title: 'Жалобы' },
    { path: '/removals', title: 'Снятие наказаний' },
    { path: '/admin', title: 'Админ-панель' },
    { path: '/bot', title: 'Статус бота' },
]

function getDocumentTitle(pathname: string) {
    if (pathname === '/') {
        return APP_TITLE
    }

    const matchedRoute = routeTitles.find(({ path }) =>
        matchPath({ path, end: true }, pathname)
    )

    if (!matchedRoute) {
        return formatDocumentTitle(['Страница не найдена'])
    }

    return formatDocumentTitle([matchedRoute.title])
}

function DocumentTitleSync() {
    const location = useLocation()

    useEffect(() => {
        document.title = getDocumentTitle(location.pathname)
    }, [location.pathname])

    return null
}

function SiteMaintenanceNavigator() {
    const navigate = useNavigate()

    useEffect(() => onSiteMaintenance(({ message }) => {
        navigate('/maintenance', {
            replace: true,
            state: { message },
        })
    }), [navigate])

    return null
}

function App() {
    return (
        <Router>
            <DocumentTitleSync />
            <SiteMaintenanceNavigator />
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/maintenance" element={<MaintenancePage />} />

                <Route element={<ProtectedRoute />}>
                    <Route element={<MainLayout />}>
                        <Route path="/hub" element={<MainHub />} />
                        <Route
                            path="/assistants/:id"
                            element={
                                <PermissionRoute requireAny={['assistants.view']}>
                                    <UserProfile />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/media"
                            element={
                                <PermissionRoute requireAny={['media.view']}>
                                    <MediaList />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/media/:id"
                            element={
                                <PermissionRoute requireAny={['media.view']}>
                                    <MediaProfile />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/assistants"
                            element={
                                <PermissionRoute requireAny={['assistants.view']}>
                                    <PRStats />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/assistants/weekly/manage"
                            element={
                                <PermissionRoute requireAny={['assistants.weekly.manage']}>
                                    <AssistantWeeklyStatsPage />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/logs"
                            element={
                                <PermissionRoute requireAny={['logs.assistant_actions.view', 'logs.admin.view']}>
                                    <SpectateLogs />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/returns"
                            element={
                                <PermissionRoute requireAny={['returns.queue.view', 'returns.history.view']}>
                                    <PunishmentReturns />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/complaints"
                            element={
                                <PermissionRoute requireAny={['complaints.queue.view', 'complaints.history.view']}>
                                    <ComplaintsPage />
                                </PermissionRoute>
                            }
                        />
                        <Route
                            path="/removals"
                            element={
                                <PermissionRoute requireAny={['removals.queue.view', 'removals.history.view']}>
                                    <PunishmentRemovals />
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
                                <PermissionRoute requireAny={['monitoring.view']}>
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
