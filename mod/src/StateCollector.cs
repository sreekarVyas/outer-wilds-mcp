using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace GameContextProvider
{
    /// <summary>
    /// Reads game state on the Unity main thread and hands finished snapshots to a writer.
    ///
    /// Deliberately contains no BepInEx types, so this class can be driven by any loader.
    /// Strictly read-only: it calls getters and nothing else.
    /// </summary>
    public sealed class StateCollector : MonoBehaviour
    {
        /// <summary>How often to sample. 10 Hz is far faster than a human asks questions.</summary>
        public float SampleInterval = 0.1f;

        public Action<StateSnapshot> OnSnapshot;
        public Action<string> LogWarning;

        /// <summary>Optional. Records every sector ever entered, so nothing is lost between reads.</summary>
        public DiscoveryLog Discoveries;

        private float _nextSampleTime;

        // Every AstroObject.Name that Locator can actually resolve. Locator.GetAstroObject
        // returns null for the rest, so there is no point asking for them each frame.
        private static readonly AstroObject.Name[] ResolvableBodies =
        {
            AstroObject.Name.Sun,
            AstroObject.Name.CaveTwin,
            AstroObject.Name.TowerTwin,
            AstroObject.Name.TimberHearth,
            AstroObject.Name.BrittleHollow,
            AstroObject.Name.GiantsDeep,
            AstroObject.Name.DarkBramble,
            AstroObject.Name.Comet,
            AstroObject.Name.WhiteHole,
            AstroObject.Name.QuantumMoon,
            AstroObject.Name.ProbeCannon,
            AstroObject.Name.RingWorld,
            AstroObject.Name.DreamWorld,
        };

        // SectorDetector._sectorList is protected. Reflection is the cheapest way to the
        // full stack; the public API only offers "am I in sector X" one name at a time.
        private static readonly FieldInfo SectorListField =
            typeof(SectorDetector).GetField("_sectorList", BindingFlags.NonPublic | BindingFlags.Instance);

        // Locator._entryLocationsByID holds every ship-log marker in the loaded scene.
        // Locator.GetEntryLocation only answers by id, and we need the nearest one, so
        // read the dictionary directly.
        private static readonly FieldInfo EntryLocationsField =
            typeof(Locator).GetField("_entryLocationsByID", BindingFlags.NonPublic | BindingFlags.Static);

        /// <summary>How many nearby ship-log locations to report.</summary>
        private const int MaxNearbyEntries = 3;

        /// <summary>Ignore markers further away than this; they describe a different place.</summary>
        private const float NearbyEntryRadius = 1000f;

        private static readonly HazardVolume.HazardType[] HazardTypes =
        {
            HazardVolume.HazardType.GENERAL,
            HazardVolume.HazardType.DARKMATTER,
            HazardVolume.HazardType.HEAT,
            HazardVolume.HazardType.FIRE,
            HazardVolume.HazardType.SANDFALL,
            HazardVolume.HazardType.ELECTRICITY,
            HazardVolume.HazardType.RAPIDS,
        };

        /// <summary>
        /// Reports which private fields this collector could not find.
        ///
        /// Both reflection targets are private game internals. If a game update renames
        /// one, the collector keeps running and silently emits empty data forever, which
        /// looks like "the player is nowhere" rather than like a fault. Call this at
        /// startup and log the result, so the failure is visible immediately.
        /// </summary>
        public static List<string> SelfCheck()
        {
            var problems = new List<string>();

            if (SectorListField == null)
                problems.Add("SectorDetector._sectorList not found — sector stack will always be empty");

            if (EntryLocationsField == null)
                problems.Add("Locator._entryLocationsByID not found — no ship-log place names");

            return problems;
        }

        private void Update()
        {
            if (Time.unscaledTime < _nextSampleTime) return;
            _nextSampleTime = Time.unscaledTime + SampleInterval;

            StateSnapshot snapshot;
            try
            {
                snapshot = Build();
            }
            catch (Exception e)
            {
                // A throw here every frame would spam the log and stall the game.
                // Emit an out-of-game snapshot instead and keep going.
                LogWarning?.Invoke("snapshot build failed: " + e.Message);
                snapshot = OutOfGame();
            }

            if (Discoveries != null && snapshot.InGame)
            {
                Discoveries.Observe(snapshot.Sectors, snapshot.Body);
                Discoveries.FlushIfDirty();
            }

            OnSnapshot?.Invoke(snapshot);
        }

        private static StateSnapshot OutOfGame()
        {
            return new StateSnapshot
            {
                Timestamp = Now(),
                Scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name,
                InGame = false,
            };
        }

        private StateSnapshot Build()
        {
            var playerBody = Locator.GetPlayerBody();
            var playerTransform = Locator.GetPlayerTransform();

            // Locator is populated only once a real scene is running.
            if (playerBody == null || playerTransform == null) return OutOfGame();

            var playerPos = playerTransform.position;
            var body = FindNearestBody(playerPos);

            // Direction is meaningful only relative to where the player looks and which
            // way is up, so both are resolved once and shared by every target below.
            var camera = Locator.GetPlayerCamera();
            var cameraTransform = camera != null ? camera.transform : null;
            var up = LocalUp(body, playerPos, cameraTransform);

            var snapshot = new StateSnapshot
            {
                Timestamp = Now(),
                Scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name,
                InGame = true,
                Body = BodyKey(body),
                Sectors = ReadSectorStack(),
                Hazards = ReadHazards(),
                Loop = ReadLoop(),
                Player = ReadPlayer(playerBody, playerPos, body),
                Ship = Describe(Locator.GetShipTransform(), playerPos, cameraTransform, up),
                Probe = Describe(ProbeTransform(), playerPos, cameraTransform, up),
                NearbyEntries = ReadNearbyEntries(playerPos, cameraTransform, up),
            };

            return snapshot;
        }

        private static StateSnapshot.LoopState ReadLoop()
        {
            return new StateSnapshot.LoopState
            {
                Count = TimeLoop.GetLoopCount(),
                Elapsed = TimeLoop.GetSecondsElapsed(),
                Remaining = TimeLoop.GetSecondsRemaining(),
                Flowing = TimeLoop.IsTimeFlowing(),
            };
        }

        private StateSnapshot.PlayerInfo ReadPlayer(OWRigidbody playerBody, Vector3 playerPos, AstroObject body)
        {
            var info = new StateSnapshot.PlayerInfo
            {
                InShip = PlayerState.IsInsideShip(),
                Suited = PlayerState.IsWearingSuit(),
                Dead = PlayerState.IsDead(),
                ZeroG = PlayerState.InZeroG(),
                Underwater = PlayerState.IsCameraUnderwater(),
                InDreamWorld = PlayerState.InDreamWorld(),
                AtFlightConsole = PlayerState.AtFlightConsole(),
            };

            var controller = Locator.GetPlayerController();
            info.Grounded = controller != null && controller.IsGrounded();

            if (body != null)
            {
                // The whole point: express position in the body's frame, not the world's.
                var local = body.transform.InverseTransformPoint(playerPos);
                info.Local = new[] { local.x, local.y, local.z };
                info.RadialDistance = local.magnitude;

                if (local.magnitude > 0.001f)
                {
                    info.Latitude = Mathf.Asin(local.y / local.magnitude) * Mathf.Rad2Deg;
                    info.Longitude = Mathf.Atan2(local.z, local.x) * Mathf.Rad2Deg;
                }

                var bodyRigidbody = body.GetOWRigidbody();
                info.Speed = bodyRigidbody != null
                    ? playerBody.GetRelativeVelocity(bodyRigidbody).magnitude
                    : playerBody.GetVelocity().magnitude;
            }
            else
            {
                info.Speed = playerBody.GetVelocity().magnitude;
            }

            return info;
        }

        /// <summary>
        /// The sector stack, outermost first. This is the richest semantic signal the game
        /// offers — the engine maintains it for streaming, and it names places directly.
        /// </summary>
        private List<string> ReadSectorStack()
        {
            var result = new List<string>();
            var detector = Locator.GetPlayerSectorDetector();
            if (detector == null || SectorListField == null) return result;

            if (!(SectorListField.GetValue(detector) is List<Sector> sectors)) return result;

            foreach (var sector in sectors)
            {
                if (sector == null) continue;
                result.Add(SectorKey(sector));
            }

            return result;
        }

        /// <summary>
        /// Best available identifier for a sector.
        ///
        /// Most sectors leave _idString empty and _name at Unnamed, so those two alone
        /// collapse half the world into "Unnamed". The GameObject name is authored per
        /// sector ("Sector_Village", "Sector_Observatory") and is the reliable key.
        /// </summary>
        private static string SectorKey(Sector sector)
        {
            var id = sector.GetIDString();
            if (!string.IsNullOrEmpty(id)) return id;

            var name = sector.GetName();
            if (name != Sector.Name.Unnamed) return name.ToString();

            var objectName = sector.gameObject != null ? sector.gameObject.name : null;
            return !string.IsNullOrEmpty(objectName) ? objectName : "Unnamed";
        }

        /// <summary>
        /// The nearest ship-log entry markers, closest first.
        ///
        /// These are the game's own names for places — "Old Settlement", "Tower of
        /// Quantum Knowledge" — placed by the designers at the right spot. They are far
        /// more reliable than reading meaning into a sector id.
        ///
        /// Note: this reports markers regardless of whether the player has discovered
        /// the entry. Filtering by discovery belongs on the consumer side.
        /// </summary>
        private List<StateSnapshot.EntryInfo> ReadNearbyEntries(Vector3 playerPos, Transform camera, Vector3 up)
        {
            var result = new List<StateSnapshot.EntryInfo>();
            if (EntryLocationsField == null) return result;

            if (!(EntryLocationsField.GetValue(null) is Dictionary<string, ShipLogEntryLocation> locations))
                return result;

            foreach (var pair in locations)
            {
                var location = pair.Value;
                if (location == null) continue;

                var position = location.GetPosition();
                var distance = Vector3.Distance(position, playerPos);
                if (distance > NearbyEntryRadius) continue;

                ComputeDirection(position, playerPos, camera, up, out var bearing, out var elevation);

                result.Add(new StateSnapshot.EntryInfo
                {
                    Id = pair.Key,
                    Name = location.GetEntryName(false),
                    Distance = distance,
                    Bearing = bearing,
                    Elevation = elevation,
                });
            }

            result.Sort((a, b) => a.Distance.CompareTo(b.Distance));
            if (result.Count > MaxNearbyEntries) result.RemoveRange(MaxNearbyEntries, result.Count - MaxNearbyEntries);
            return result;
        }

        private List<string> ReadHazards()
        {
            var result = new List<string>();

            var detectorObject = Locator.GetPlayerDetector();
            if (detectorObject == null) return result;

            var hazardDetector = detectorObject.GetComponent<HazardDetector>();
            if (hazardDetector == null) return result;

            foreach (var type in HazardTypes)
            {
                if (hazardDetector.InHazardType(type)) result.Add(type.ToString().ToLowerInvariant());
            }

            return result;
        }

        /// <summary>
        /// Direction from the player to a world point, as the player experiences it.
        ///
        /// "61 metres away" does not help anyone find something. What helps is "to your
        /// right and below you". Two angles carry that:
        ///
        ///   bearing   — degrees around the local up axis from where the camera looks.
        ///               0 ahead, +90 right, -90 left, ±180 behind.
        ///   elevation — degrees above the local horizon. Positive up, negative down.
        ///
        /// "Up" is away from the centre of the current body, not Unity's world up, because
        /// on a sphere the player's up changes with every step. Without a body — deep
        /// space — there is no meaningful horizon, so elevation falls back to the camera's
        /// own up axis.
        /// </summary>
        private static void ComputeDirection(
            Vector3 target, Vector3 playerPos, Transform camera, Vector3 up,
            out float? bearing, out float? elevation)
        {
            bearing = null;
            elevation = null;

            if (camera == null) return;

            var toTarget = target - playerPos;
            if (toTarget.sqrMagnitude < 0.0001f) return;

            var direction = toTarget.normalized;

            // Elevation: how far off the tangent plane the target sits.
            elevation = Mathf.Asin(Mathf.Clamp(Vector3.Dot(direction, up), -1f, 1f)) * Mathf.Rad2Deg;

            // Bearing: both vectors flattened onto the tangent plane, then a signed angle.
            var flatTarget = Vector3.ProjectOnPlane(direction, up);
            var flatForward = Vector3.ProjectOnPlane(camera.forward, up);

            // Looking straight up or down leaves no horizontal component to compare.
            if (flatTarget.sqrMagnitude < 0.0001f || flatForward.sqrMagnitude < 0.0001f) return;

            bearing = Vector3.SignedAngle(flatForward, flatTarget, up);
        }

        /// <summary>Local up: away from the body's centre, or the camera's up in deep space.</summary>
        private static Vector3 LocalUp(AstroObject body, Vector3 playerPos, Transform camera)
        {
            if (body != null)
            {
                var fromCentre = playerPos - body.transform.position;
                if (fromCentre.sqrMagnitude > 0.0001f) return fromCentre.normalized;
            }

            return camera != null ? camera.up : Vector3.up;
        }

        /// <summary>Nearest body by centre distance. Good enough: you are normally closest to what you are standing on.</summary>
        private static AstroObject FindNearestBody(Vector3 position)
        {
            AstroObject nearest = null;
            var nearestDistance = float.MaxValue;

            foreach (var name in ResolvableBodies)
            {
                var candidate = Locator.GetAstroObject(name);
                if (candidate == null) continue;

                var distance = (candidate.transform.position - position).sqrMagnitude;
                if (distance >= nearestDistance) continue;

                nearestDistance = distance;
                nearest = candidate;
            }

            return nearest;
        }

        /// <summary>
        /// Stable machine-readable body key, e.g. "BrittleHollow".
        /// Not AstroObject.AstroObjectNameToString — that returns localized display text,
        /// and literally "ERROR" for DreamWorld and WhiteHoleTarget.
        /// </summary>
        private static string BodyKey(AstroObject body)
        {
            return body == null ? null : body.GetAstroObjectName().ToString();
        }

        private static Transform ProbeTransform()
        {
            var probe = Locator.GetProbe();
            // The probe object exists before it is ever launched; report it only when in flight.
            return probe != null && probe.IsLaunched() ? probe.transform : null;
        }

        private static StateSnapshot.ObjectInfo Describe(
            Transform target, Vector3 playerPos, Transform camera, Vector3 up)
        {
            if (target == null) return new StateSnapshot.ObjectInfo();

            ComputeDirection(target.position, playerPos, camera, up, out var bearing, out var elevation);

            return new StateSnapshot.ObjectInfo
            {
                Distance = Vector3.Distance(target.position, playerPos),
                Body = BodyKey(FindNearestBody(target.position)),
                Bearing = bearing,
                Elevation = elevation,
            };
        }

        private static double Now()
        {
            return (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        }
    }
}
