from agentbay import AgentBay, CreateSessionParams
from agentbay.api.models import ExtraConfigs, MobileExtraConfig, AppManagerRule
from dotenv import load_dotenv
import os
import signal
import sys
import time
import atexit
import re
from typing import List

load_dotenv()


class MobileSessionManager:
    """Manages mobile session with automatic cleanup"""

    def __init__(self, api_key: str):
        self.agent_bay = AgentBay(api_key=api_key)
        self.session = None
        self._setup_cleanup_handlers()

    def _setup_cleanup_handlers(self):
        """Setup signal handlers and atexit for automatic cleanup"""
        # Register atexit handler
        atexit.register(self._cleanup)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle interrupt signals (Ctrl+C, etc.)"""
        print(f"\n\n⚠️  Received signal {signum}, cleaning up...")
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        """Cleanup session if it exists"""
        if self.session:
            try:
                print("\n=== Cleaning Up Session ===")
                delete_result = self.agent_bay.delete(self.session)
                if delete_result.success:
                    print(f"✅ Session {self.session.session_id} deleted successfully")
                else:
                    print(f"❌ Failed to delete session: {delete_result.error_message}")
                self.session = None
            except Exception as e:
                print(f"❌ Exception during cleanup: {e}")

    def _extract_package_name(self, start_cmd: str) -> str:
        """Extract Android package name from start command"""
        match = re.search(r'-p\s+([a-zA-Z0-9_.]+)', start_cmd)
        if match:
            return match.group(1)
        return None

    def create_session(self):
        """Create a new mobile session without extra configs"""
        print("=== Creating Mobile Session ===")

        params = CreateSessionParams(
            image_id="mobile_latest",
            labels={"project": "mobile-testing", "environment": "development"},
        )

        session_result = self.agent_bay.create(params)
        self.session = session_result.session
        print(f"✅ Session created: {self.session.session_id}")

        return self.session

    def get_session_info(self):
        """Get session information"""
        print("\n=== Getting Session Info ===")
        info_result = self.session.info()
        if info_result.success:
            session_info = info_result.data
            print("📋 Session Info:")
            print(f"   Session ID: {session_info.session_id}")
            print(f"   Resource URL: {session_info.resource_url}")
            if session_info.resource_type:
                print(f"   Resource Type: {session_info.resource_type}")
            if session_info.ticket:
                print(f"   Ticket: {session_info.ticket}")
            return session_info
        else:
            print(f"❌ Failed to get session info: {info_result.error_message}")
            return None

    def execute_command(self, command: str):
        """Execute a command on the mobile session"""
        print(f"\n=== Executing Command ===")
        print(f"Command: {command}")
        try:
            result = self.session.command.execute_command(command)
            print(f"✅ Command output: {result.output}")
            return result.output
        except Exception as e:
            print(f"❌ Failed to execute command: {e}")
            return None

    def get_installed_apps(self, print_details: bool = True):
        """Get list of installed apps on the mobile session"""
        print(f"\n=== Getting Installed Apps ===")
        try:
            result = self.session.mobile.get_installed_apps(
                start_menu=True,
                desktop=False,
                ignore_system_apps=True
            )

            if result.success:
                apps = result.data
                print(f"✅ Found {len(apps)} installed applications")

                if apps and print_details:
                    for i, app in enumerate(apps, 1):
                        print(f"\n📱 App {i}/{len(apps)}:")
                        print(f"   Name: {app.name}")
                        print(f"   Start Command: {app.start_cmd}")
                        print(f"   Stop Command: {app.stop_cmd if app.stop_cmd else 'N/A'}")
                        print(f"   Work Directory: {app.work_directory if app.work_directory else 'N/A'}")
                        print("   ---")
                elif not apps:
                    print("   No apps found")

                return apps
            else:
                print(f"❌ Failed to get installed apps: {result.error_message}")
                return None
        except Exception as e:
            print(f"❌ Exception while getting installed apps: {e}")
            return None

    def extract_package_names_from_apps(self, apps):
        """Extract package names from list of installed apps"""
        package_names = []
        if not apps:
            return package_names

        for app in apps:
            package_name = self._extract_package_name(app.start_cmd)
            if package_name:
                package_names.append(package_name)
            else:
                print(f"⚠️  Could not extract package name from: {app.start_cmd}")

        return package_names

    def verify_app_uninstalled(self, package_name: str) -> bool:
        """Verify if an app is uninstalled by checking pm list packages"""
        try:
            result = self.session.command.execute_command(f"pm list packages | grep {package_name}")
            if result.success:
                output = result.output.strip()
                # If grep finds the package, it means the app still exists
                return len(output) == 0
            return False
        except Exception as e:
            print(f"   ⚠️  Exception during verification: {e}")
            return False

    def uninstall_app(self, package_name: str, app_name: str = None) -> bool:
        """Uninstall a single app using multiple strategies"""
        display_name = app_name if app_name else package_name
        print(f"\n🗑️  Uninstalling: {display_name}")
        print(f"   Package: {package_name}")

        # Strategy 1: pm uninstall --user 0 (safest, user-level uninstall)
        # print(f"   Trying: pm uninstall --user 0...")
        # result = self.session.command.execute_command(f"pm uninstall --user 0 {package_name}")
        # if result.success and ("Success" in result.output or "success" in result.output.lower()):
        #     print(f"   ✅ Successfully uninstalled (user level)")
        #     return True

        # Strategy 2: pm disable-user (disable the app)
        print(f"   Trying: pm disable-user --user 0...")
        result = self.session.command.execute_command(f"pm disable-user --user 0 {package_name}")
        if result.success and ("disabled" in result.output.lower() or "new state" in result.output.lower()):
            print(f"   ✅ Successfully disabled")
            return True

        # # Strategy 3: pm hide (hide the app)
        # print(f"   Trying: pm hide --user 0...")
        # result = self.session.command.execute_command(f"pm hide --user 0 {package_name}")
        # if result.success and ("true" in result.output.lower() or "hidden" in result.output.lower()):
        #     print(f"   ✅ Successfully hidden")
        #     return True

        # # Strategy 4: pm uninstall (complete uninstall, may require root)
        # print(f"   Trying: pm uninstall...")
        # result = self.session.command.execute_command(f"pm uninstall {package_name}")
        # if result.success and ("Success" in result.output or "success" in result.output.lower()):
        #     print(f"   ✅ Successfully uninstalled (complete)")
        #     return True

        # print(f"   ❌ All uninstall strategies failed")
        return False

    def uninstall_apps(self, apps_with_packages: List[tuple]) -> dict:
        """
        Uninstall multiple apps
        Args:
            apps_with_packages: List of tuples (app_name, package_name)
        Returns:
            dict with success_count, failed_count, and results list
        """
        print("\n" + "="*60)
        print("Starting App Uninstallation")
        print("="*60)

        results = []
        success_count = 0
        failed_count = 0

        for app_name, package_name in apps_with_packages:
            success = self.uninstall_app(package_name, app_name)

            # Verify uninstallation
            is_removed = self.verify_app_uninstalled(package_name)

            if success or is_removed:
                results.append({"app": app_name, "package": package_name, "status": "success"})
                success_count += 1
            else:
                results.append({"app": app_name, "package": package_name, "status": "failed"})
                failed_count += 1

        print("\n" + "="*60)
        print("Uninstallation Summary")
        print("="*60)
        print(f"✅ Successfully removed: {success_count}")
        print(f"❌ Failed to remove: {failed_count}")
        print(f"📊 Total processed: {success_count + failed_count}")

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }


def main():
    """Main execution flow"""
    api_key = os.getenv("AGENTBAY_API_KEY")
    if not api_key:
        print("❌ AGENTBAY_API_KEY not found in environment")
        return

    # Create session manager (cleanup will happen automatically)
    manager = MobileSessionManager(api_key)

    try:
        # Create session
        manager.create_session()

        # Get session info
        manager.get_session_info()

        # Execute test command
        manager.execute_command("echo 'Hello AgentBay'")

        # Get installed apps BEFORE uninstallation
        print("\n" + "="*60)
        print("PHASE 1: Query installed apps")
        print("="*60)
        apps = manager.get_installed_apps(print_details=True)

        if apps and len(apps) > 0:
            # Extract package names and prepare for uninstallation
            apps_to_uninstall = []
            for app in apps:
                package_name = manager._extract_package_name(app.start_cmd)
                if package_name:
                    apps_to_uninstall.append((app.name, package_name))

            print(f"\n📋 Found {len(apps_to_uninstall)} apps to uninstall")

            # Uninstall all apps
            print("\n" + "="*60)
            print("PHASE 2: Uninstall all apps")
            print("="*60)
            start = time.time()
            # uninstall_results = manager.uninstall_apps(apps_to_uninstall)
            end = time.time()
            print(f"Time taken: {end - start} seconds")

            # Verify by querying apps again
            print("\n" + "="*60)
            print("PHASE 3: Verify uninstallation")
            print("="*60)
            remaining_apps = manager.get_installed_apps(print_details=False)

            if remaining_apps and len(remaining_apps) > 0:
                print(f"\n⚠️  {len(remaining_apps)} apps still remaining:")
                for app in remaining_apps:
                    print(f"   - {app.name}")
            else:
                print("\n✅ All apps successfully removed!")
                print("   The device is now clean")

        else:
            print("\n✅ No apps found to uninstall")

        # Simulate long-running process
        print("\n⏳ Running for 60 seconds... (Press Ctrl+C to stop)")
        time.sleep(60 * 60 * 24)

        print("\n✅ Process completed normally")

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        # Cleanup will be called automatically by atexit
        print("\n👋 Exiting...")


if __name__ == "__main__":
    main()