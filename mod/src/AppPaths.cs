using System;
using System.IO;

namespace GameContextProvider
{
    /// <summary>
    /// Where the plugin writes its runtime files.
    ///
    /// Deliberately not the game folder. The plugin knows where it is installed; the MCP
    /// server does not, and making the server hunt for the game install is the harder
    /// half of a problem that disappears entirely if both sides derive the same path
    /// from the OS instead.
    ///
    /// Must stay in step with gcp/config.py — the Python side computes this identically.
    /// </summary>
    public static class AppPaths
    {
        public const string AppName = "GameContextProvider";

        /// <summary>Namespaced per game, so a second adapter does not collide with this one.</summary>
        public const string GameKey = "outer-wilds";

        public const string SnapshotFile = "snapshot.json";
        public const string ShipLogFile = "shiplog.json";
        public const string SectorsFile = "sectors-seen.json";

        /// <summary>%LOCALAPPDATA%\GameContextProvider\outer-wilds</summary>
        public static string DataDirectory
        {
            get
            {
                var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

                // Mono can return an empty string when the folder is unknown rather than
                // throwing. Fall back to the user profile so the plugin still runs.
                if (string.IsNullOrEmpty(localAppData))
                {
                    localAppData = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                        "AppData", "Local");
                }

                return Path.Combine(localAppData, AppName, GameKey);
            }
        }

        public static string Snapshot => Path.Combine(DataDirectory, SnapshotFile);
        public static string ShipLog => Path.Combine(DataDirectory, ShipLogFile);
        public static string Sectors => Path.Combine(DataDirectory, SectorsFile);
    }
}
