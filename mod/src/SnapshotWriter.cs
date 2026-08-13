using System;
using System.IO;
using System.Threading;
using Newtonsoft.Json;

namespace GameContextProvider
{
    /// <summary>
    /// Writes the newest snapshot to disk from a background thread.
    ///
    /// The Unity thread must never block on file IO, and the writer thread must never
    /// touch a Unity object — doing so crashes the process. The only thing crossing the
    /// boundary is a finished, immutable snapshot published through a volatile field.
    /// Snapshots are lossy by design: if the writer falls behind, older ones are dropped.
    /// </summary>
    public sealed class SnapshotWriter : IDisposable
    {
        private readonly string _path;
        private readonly string _tempPath;
        private readonly Thread _thread;
        private readonly ManualResetEventSlim _pending = new ManualResetEventSlim(false);
        private readonly Action<string> _logWarning;

        private volatile StateSnapshot _latest;
        private volatile bool _running = true;

        public SnapshotWriter(string path, Action<string> logWarning = null)
        {
            _path = path;
            _tempPath = path + ".tmp";
            _logWarning = logWarning;

            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

            _thread = new Thread(Loop)
            {
                Name = "GameContextProvider.SnapshotWriter",
                IsBackground = true, // must not keep the process alive on quit
            };
            _thread.Start();
        }

        /// <summary>Called from the Unity thread. Never blocks.</summary>
        public void Publish(StateSnapshot snapshot)
        {
            _latest = snapshot;
            _pending.Set();
        }

        private void Loop()
        {
            while (_running)
            {
                _pending.Wait();
                _pending.Reset();
                if (!_running) break;

                var snapshot = _latest;
                if (snapshot == null) continue;

                try
                {
                    var json = JsonConvert.SerializeObject(snapshot, Formatting.Indented);
                    File.WriteAllText(_tempPath, json);
                    AtomicReplace(_tempPath, _path);
                }
                catch (Exception e)
                {
                    _logWarning?.Invoke("snapshot write failed: " + e.Message);
                    Thread.Sleep(1000); // a failing disk should not spin this thread
                }
            }
        }

        /// <summary>
        /// Replace <paramref name="destination"/> with <paramref name="temp"/> in one step.
        ///
        /// Delete-then-move leaves a window where the file does not exist. A reader
        /// polling at the same time then sees nothing and reports the game as closed.
        /// File.Replace has no such window. It needs the destination to exist, so the
        /// first write of a session falls back to Move.
        /// </summary>
        internal static void AtomicReplace(string temp, string destination)
        {
            if (File.Exists(destination))
            {
                File.Replace(temp, destination, null);
            }
            else
            {
                File.Move(temp, destination);
            }
        }

        public void Dispose()
        {
            _running = false;
            _pending.Set();
            _thread?.Join(TimeSpan.FromSeconds(2));
            _pending.Dispose();
        }
    }
}
