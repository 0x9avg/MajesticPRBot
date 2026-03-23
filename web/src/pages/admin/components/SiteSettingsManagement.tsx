import RbacManagement from './RbacManagement';
import SiteMaintenanceManagement from './SiteMaintenanceManagement';

const SiteSettingsManagement = () => (
    <div className="space-y-6">
        <RbacManagement />
        <SiteMaintenanceManagement />
    </div>
);

export default SiteSettingsManagement;
