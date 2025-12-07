using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace NineSolTrainerApp
{
    /// <summary>
    /// Main trainer behaviour.
    /// Implements per-feature "boost" values that go up on hits
    /// within a short interval and decay over time when not hitting.
    /// </summary>
    internal class NineSolTrainerMain : MonoBehaviour
    {
        // ---------------------------------------------------------------------
        // Public configuration (max multipliers)
        // ---------------------------------------------------------------------

        // Damage: 1x .. DamageMultiplier
        public static bool DamageHackEnabled = true;
        public static float DamageMultiplier = 3.0f;

        // Melee cooldown / animation speed: 1x .. MeleeCooldownSpeedMultiplier
        public static float MeleeCooldownSpeedMultiplier = 3.0f;

        // Hitbox size: 1x .. HitboxScale
        public static bool HitboxHackEnabled = true;
        public static float HitboxScale = 6.0f;

        // Interval in seconds during which consecutive hits keep stacking boost.
        private const float HitIntervalSeconds = 1.0f;

        // ---------------------------------------------------------------------
        // Boost model
        // ---------------------------------------------------------------------

        private struct FeatureBoost
        {
            public float Current;         // 0..Max
            public float Max;             // Max boost value
            public float IncreasePerHit;  // Amount added per hit
            public float DecayPerSecond;  // Amount subtracted per second (after interval)
            public float LastHitTime;     // Time.time of last hit

            public float Normalized
            {
                get { return Max > 0f ? Mathf.Clamp01(Current / Max) : 0f; }
            }
        }

        // One boost value per hack feature
        private static FeatureBoost _damageBoost;
        private static FeatureBoost _cooldownBoost;
        private static FeatureBoost _hitboxBoost;

        // Attack state derived from Player.AttackPressed
        private static bool _lastAttackPressed;
        private static bool _isAttacking;
        private static float _attackStartTime;

        // ---------------------------------------------------------------------
        // EffectDealer / damage reflection support
        // ---------------------------------------------------------------------

        private static FieldInfo _valueField;
        private static FieldInfo _valueProviderField;
        private static PropertyInfo _hasValueProviderProp;

        // Cache each dealer's original base value so we can apply
        // boost as a pure multiplier and restore when boost is zero.
        private static readonly Dictionary<EffectDealer, float> OriginalDealerValue =
            new Dictionary<EffectDealer, float>();

        // ---------------------------------------------------------------------
        // Hitbox scaling support
        // ---------------------------------------------------------------------

        private struct ColliderOriginalData
        {
            public Vector2 BoxSize;
            public Vector2 BoxOffset;
            public float CircleRadius;
            public Vector2 CapsuleSize;
            public Vector3 TransformScale;
            public bool IsBox;
            public bool IsCircle;
            public bool IsCapsule;
        }

        private static readonly Dictionary<Collider2D, ColliderOriginalData> OriginalColliderData =
            new Dictionary<Collider2D, ColliderOriginalData>();

        // ---------------------------------------------------------------------
        // Melee cooldown / animation state
        // ---------------------------------------------------------------------

        private static float _baseMeleeCooldown = -1f;
        private static float _baseAnimatorSpeed = -1f;

        // ---------------------------------------------------------------------
        // HUD / debug
        // ---------------------------------------------------------------------

        private bool _showHud = true;

        private static string _debugAttackDealerName = string.Empty;
        private static float _debugAttackBaseValue;
        private static float _debugAttackNewValue;

        private static float _debugBaseMeleeCooldown;
        private static float _debugCurrentMeleeCooldown;
        private static float _debugBaseAnimatorSpeed;
        private static float _debugCurrentAnimatorSpeed;

        private static string _debugColliderName = string.Empty;
        private static string _debugColliderType = string.Empty;
        private static Vector2 _debugOriginalSize;
        private static Vector2 _debugCurrentSize;
        private static float _debugOriginalRadius;
        private static float _debugCurrentRadius;

        // Extra debug for damage hack internals
        private static float _debugDamageBoostNormalized;
        private static float _debugDamageMultiplierApplied;
        private static float _debugDamageTargetValue;
        private static float _debugDamageFinalBefore;
        private static float _debugDamageFinalAfter;
        private static float _debugDamageFieldBefore;
        private static float _debugDamageFieldAfter;
        private static float _debugDamageProviderBefore;
        private static float _debugDamageProviderAfter;
        private static bool _debugDamageHasProvider;
        private static bool _debugDamageUsedProvider;
        private static bool _debugDamageUsedField;
        private static string _debugDamageLastError;

        private void Awake()
        {
            // Cache reflection info on EffectDealer once
            if (_valueField == null)
            {
                var t = typeof(EffectDealer);
                _valueField = t.GetField("value",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                _valueProviderField = t.GetField("valueProvider",
                    BindingFlags.Instance | BindingFlags.NonPublic);
                _hasValueProviderProp = t.GetProperty("HasValueProvider",
                    BindingFlags.Instance | BindingFlags.NonPublic);
            }

            // Initialise boost configs (0..MaxMultiplier)
            InitBoost(ref _damageBoost, DamageMultiplier);
            InitBoost(ref _cooldownBoost, MeleeCooldownSpeedMultiplier);
            InitBoost(ref _hitboxBoost, HitboxScale);
        }

        private static void InitBoost(ref FeatureBoost boost, float max)
        {
            max = Mathf.Max(0f, max);
            boost.Max = max;
            boost.Current = 0f;
            boost.LastHitTime = -999f;

            // Heuristic: reach near-max in ~12 hits (smaller step per attack),
            // decay to zero in ~2 seconds.
            boost.IncreasePerHit = max * (0.25f / 3f); // one-third of original step
            boost.DecayPerSecond = max * 0.5f;
        }

        private void Update()
        {
            HandleHotkeys();
            UpdateFeatureBoosts();
            ApplyDamageHack();
            ApplyMeleeCooldownHack();
            ApplyHitboxHack();
        }

        // ---------------------------------------------------------------------
        // Input / boost updates
        // ---------------------------------------------------------------------

        private void HandleHotkeys()
        {
            if (Input.GetKeyDown(KeyCode.F5))
            {
                DamageHackEnabled = !DamageHackEnabled;
                Debug.Log($"[NineSolTrainer] DamageHack: {DamageHackEnabled}");
            }

            if (Input.GetKeyDown(KeyCode.F6))
            {
                HitboxHackEnabled = !HitboxHackEnabled;
                Debug.Log($"[NineSolTrainer] HitboxHack: {HitboxHackEnabled}");
            }

            if (Input.GetKeyDown(KeyCode.F7))
            {
                _showHud = !_showHud;
            }
        }

        /// <summary>
        /// Update all feature boosts based on completed attacks and elapsed time.
        /// Rules:
        /// 1. When AttackPressed becomes true, we enter "attacking" state.
        /// 2. When AttackPressed becomes false while attacking, and the attack
        ///    duration is within HitIntervalSeconds, we treat it as one completed attack
        ///    and apply boost.
        /// 3. Boost always uses cached original values as baseline when applied.
        /// </summary>
        private void UpdateFeatureBoosts()
        {
            float now = Time.time;

            var player = Player.i;
            bool attackCompletedThisFrame = false;

            if (player != null)
            {
                bool pressed = player.AttackPressed;

                // Step 1: AttackPressed true => enter attacking state and remember start time.
                if (pressed && !_lastAttackPressed)
                {
                    _isAttacking = true;
                    _attackStartTime = now;
                }
                // Step 2: AttackPressed false while attacking => attack finished.
                else if (!pressed && _lastAttackPressed && _isAttacking)
                {
                    float duration = now - _attackStartTime;
                    if (duration <= HitIntervalSeconds)
                    {
                        attackCompletedThisFrame = true;
                    }
                    _isAttacking = false;
                }

                _lastAttackPressed = pressed;
            }

            UpdateSingleBoost(ref _damageBoost, attackCompletedThisFrame, now);
            UpdateSingleBoost(ref _cooldownBoost, attackCompletedThisFrame, now);
            UpdateSingleBoost(ref _hitboxBoost, attackCompletedThisFrame, now);
        }

        /// <summary>
        /// Update a single boost value:
        /// - on hit: increase Current by IncreasePerHit
        /// - if no hit and interval elapsed: decay Current over time
        /// - always clamp Current to [0, Max]
        /// </summary>
        private static void UpdateSingleBoost(ref FeatureBoost boost, bool hitThisFrame, float now)
        {
            if (hitThisFrame)
            {
                boost.LastHitTime = now;
                boost.Current += boost.IncreasePerHit;
            }
            else if (boost.Current > 0f && (now - boost.LastHitTime) >= HitIntervalSeconds)
            {
                boost.Current -= boost.DecayPerSecond * Time.deltaTime;
            }

            boost.Current = Mathf.Clamp(boost.Current, 0f, boost.Max);
        }

        // ---------------------------------------------------------------------
        // Damage hack
        // ---------------------------------------------------------------------

        private static IEnumerable<EffectDealer> EnumeratePlayerAttackDealers()
        {
            var player = Player.i;
            if (player == null)
            {
                yield break;
            }

            if (player.normalAttackDealer != null)
            {
                yield return player.normalAttackDealer;
            }

            if (player.thirdAttackDealer != null)
            {
                yield return player.thirdAttackDealer;
            }
        }

        private void ApplyDamageHack()
        {
            foreach (var dealer in EnumeratePlayerAttackDealers())
            {
                if (dealer == null)
                {
                    continue;
                }

                try
                {
                    if (!OriginalDealerValue.TryGetValue(dealer, out var baseValue) || baseValue <= 0f)
                    {
                        // Prefer the dealer's current FinalValue as the original "base" damage,
                        // since some dealers keep their internal value field at 0.
                        float finalNow = 0f;
                        try
                        {
                            finalNow = dealer.FinalValue;
                        }
                        catch
                        {
                            // ignore
                        }

                        if (finalNow > 0f)
                        {
                            baseValue = finalNow;
                        }
                        else
                        {
                            // Fallback to reflection-based base read.
                            baseValue = ReadDealerBaseValue(dealer);
                        }

                        OriginalDealerValue[dealer] = baseValue;
                    }

                    float normalizedBoost = _damageBoost.Normalized;

                    float finalValue;
                    if (!DamageHackEnabled || normalizedBoost <= 0f)
                    {
                        // Restore original
                        finalValue = baseValue;
                    }
                    else
                    {
                        float multiplier = Mathf.Lerp(1f, DamageMultiplier, normalizedBoost);
                        finalValue = baseValue * multiplier;
                    }

                    // Debug: record working procedure for last processed dealer
                    _debugAttackDealerName = dealer.name;
                    _debugAttackBaseValue = baseValue;
                    _debugAttackNewValue = finalValue;
                    _debugDamageBoostNormalized = normalizedBoost;
                    _debugDamageMultiplierApplied = (!DamageHackEnabled || normalizedBoost <= 0f)
                        ? 1f
                        : Mathf.Lerp(1f, DamageMultiplier, normalizedBoost);
                    _debugDamageTargetValue = finalValue;
                    _debugDamageLastError = null;

                    WriteDealerBaseValue(dealer, finalValue);
                }
                catch (Exception ex)
                {
                    _debugDamageLastError = ex.Message;
                }
            }
        }

        private float ReadDealerBaseValue(EffectDealer dealer)
        {
            if (dealer == null)
            {
                return 0f;
            }

            try
            {
                // Prefer value provider if present
                bool hasProvider = false;
                if (_hasValueProviderProp != null)
                {
                    var rawHas = _hasValueProviderProp.GetValue(dealer);
                    if (rawHas is bool b)
                    {
                        hasProvider = b;
                    }
                }

                object provider = null;
                if (hasProvider && _valueProviderField != null)
                {
                    provider = _valueProviderField.GetValue(dealer);
                }

                if (provider != null)
                {
                    var prop = provider.GetType().GetProperty("Value",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (prop != null && prop.CanRead)
                    {
                        var val = prop.GetValue(provider);
                        return Convert.ToSingle(val);
                    }

                    // Fallback: provider exists but no readable Value property.
                    return dealer.FinalValue;
                }
            }
            catch
            {
                // Ignore and fall through to non-provider logic.
            }

            // Fall back to direct value field
            if (_valueField != null)
            {
                try
                {
                    var raw = _valueField.GetValue(dealer);
                    if (raw is float f)
                    {
                        return f;
                    }

                    return Convert.ToSingle(raw);
                }
                catch
                {
                    // Ignore and fall back to FinalValue.
                }
            }

            // Last resort: FinalValue
            return dealer.FinalValue;
        }

        private void WriteDealerBaseValue(EffectDealer dealer, float value)
        {
            if (dealer == null)
            {
                return;
            }

            // Reset per-write debug state
            _debugDamageHasProvider = false;
            _debugDamageUsedProvider = false;
            _debugDamageUsedField = false;
            _debugDamageProviderBefore = 0f;
            _debugDamageProviderAfter = 0f;
            _debugDamageFieldBefore = 0f;
            _debugDamageFieldAfter = 0f;
            _debugDamageFinalBefore = 0f;
            _debugDamageFinalAfter = 0f;

            try
            {
                object provider = null;

                if (_valueProviderField != null)
                {
                    provider = _valueProviderField.GetValue(dealer);
                }

                if (provider != null)
                {
                    _debugDamageHasProvider = true;

                    // Try to read provider before write
                    try
                    {
                        var propBefore = provider.GetType().GetProperty("Value",
                            BindingFlags.Public | BindingFlags.Instance);
                        if (propBefore != null && propBefore.CanRead)
                        {
                            var v = propBefore.GetValue(provider);
                            _debugDamageProviderBefore = Convert.ToSingle(v);
                        }
                    }
                    catch
                    {
                        // ignore
                    }

                    // Try to write through provider's Value property
                    var prop = provider.GetType().GetProperty("Value",
                        BindingFlags.Public | BindingFlags.Instance);
                    if (prop != null && prop.CanWrite)
                    {
                        prop.SetValue(provider, value);
                        _debugDamageUsedProvider = true;

                        // Read back after write
                        try
                        {
                            if (prop.CanRead)
                            {
                                var v = prop.GetValue(provider);
                                _debugDamageProviderAfter = Convert.ToSingle(v);
                            }
                        }
                        catch
                        {
                            // ignore
                        }
                        return;
                    }
                }
            }
            catch
            {
                // Ignore and fall through to field write.
            }

            if (_valueField != null)
            {
                try
                {
                    // Read field before write
                    try
                    {
                        var rawBefore = _valueField.GetValue(dealer);
                        if (rawBefore is float fb)
                        {
                            _debugDamageFieldBefore = fb;
                        }
                        else
                        {
                            _debugDamageFieldBefore = Convert.ToSingle(rawBefore);
                        }
                    }
                    catch
                    {
                        // ignore
                    }

                    _valueField.SetValue(dealer, value);
                    _debugDamageUsedField = true;

                    // Read field after write
                    try
                    {
                        var rawAfter = _valueField.GetValue(dealer);
                        if (rawAfter is float fa)
                        {
                            _debugDamageFieldAfter = fa;
                        }
                        else
                        {
                            _debugDamageFieldAfter = Convert.ToSingle(rawAfter);
                        }
                    }
                    catch
                    {
                        // ignore
                    }
                }
                catch
                {
                    // Ignore: trainer code.
                }
            }

            // Snapshot FinalValue before/after as well
            try
            {
                _debugDamageFinalBefore = dealer.FinalValue;
            }
            catch
            {
                // ignore
            }

            try
            {
                _debugDamageFinalAfter = dealer.FinalValue;
            }
            catch
            {
                // ignore
            }
        }

        // ---------------------------------------------------------------------
        // Melee cooldown / animation speed hack
        // ---------------------------------------------------------------------

        private void ApplyMeleeCooldownHack()
        {
            var player = Player.i;
            if (player == null)
            {
                return;
            }

            var anim = player.animator;
            if (anim != null && _baseAnimatorSpeed < 0f)
            {
                _baseAnimatorSpeed = anim.speed;
            }
            player.meleeAttackCooldownTimer = 0;
            if (anim != null && _baseAnimatorSpeed > 0f)
            {
                // Use boost mechanism only for animation speed; do not touch meleeAttackCooldownTimer.
                float boost = _cooldownBoost.Normalized;
                float speedMultiplier = boost > 0f
                    ? Mathf.Lerp(1f, MeleeCooldownSpeedMultiplier, boost)
                    : 1f;
                anim.speed = _baseAnimatorSpeed * speedMultiplier;

                _debugBaseAnimatorSpeed = _baseAnimatorSpeed;
                _debugCurrentAnimatorSpeed = anim.speed;
            }
        }

        // ---------------------------------------------------------------------
        // Hitbox hack
        // ---------------------------------------------------------------------

        private static IEnumerable<EffectDealer> EnumeratePlayerHitboxDealers()
        {
            var player = Player.i;
            if (player == null)
            {
                yield break;
            }

            if (player.normalAttackDealer != null)
            {
                yield return player.normalAttackDealer;
            }

            if (player.thirdAttackDealer != null)
            {
                yield return player.thirdAttackDealer;
            }
        }

        private void ApplyHitboxHack()
        {
            float normalizedBoost = _hitboxBoost.Normalized;

            foreach (var dealer in EnumeratePlayerHitboxDealers())
            {
                if (dealer == null)
                {
                    continue;
                }

                var colliders = new List<Collider2D>();

                if (dealer.MyCollider != null)
                {
                    colliders.Add(dealer.MyCollider);
                }

                colliders.AddRange(dealer.GetComponents<Collider2D>());
                colliders.AddRange(dealer.GetComponentsInChildren<Collider2D>(true));

                foreach (var col in colliders)
                {
                    if (col == null)
                    {
                        continue;
                    }

                    try
                    {
                        if (!OriginalColliderData.ContainsKey(col))
                        {
                            CacheOriginalCollider(col);
                        }

                        if (HitboxHackEnabled && normalizedBoost > 0f)
                        {
                            float scale = Mathf.Lerp(1f, HitboxScale, normalizedBoost);
                            ApplyColliderScale(col, scale);
                        }
                        else
                        {
                            RestoreCollider(col);
                        }
                    }
                    catch
                    {
                        // Ignore per-collider errors.
                    }
                }
            }
        }

        private static void CacheOriginalCollider(Collider2D col)
        {
            var data = new ColliderOriginalData
            {
                TransformScale = col.transform.localScale
            };

            if (col is BoxCollider2D box)
            {
                data.IsBox = true;
                data.BoxSize = box.size;
                data.BoxOffset = box.offset;
            }
            else if (col is CircleCollider2D circle)
            {
                data.IsCircle = true;
                data.CircleRadius = circle.radius;
            }
            else if (col is CapsuleCollider2D capsule)
            {
                data.IsCapsule = true;
                data.CapsuleSize = capsule.size;
            }

            OriginalColliderData[col] = data;
        }

        private static void ApplyColliderScale(Collider2D col, float scale)
        {
            if (!OriginalColliderData.TryGetValue(col, out var data))
            {
                return;
            }

            if (data.IsBox && col is BoxCollider2D box)
            {
                box.size = data.BoxSize * scale;
                box.offset = data.BoxOffset * scale;
            }
            else if (data.IsCircle && col is CircleCollider2D circle)
            {
                circle.radius = data.CircleRadius * scale;
            }
            else if (data.IsCapsule && col is CapsuleCollider2D capsule)
            {
                capsule.size = data.CapsuleSize * scale;
            }
            else
            {
                col.transform.localScale = data.TransformScale * scale;
            }

            UpdateColliderDebug(col, data);
        }

        private static void RestoreCollider(Collider2D col)
        {
            if (!OriginalColliderData.TryGetValue(col, out var data))
            {
                return;
            }

            if (data.IsBox && col is BoxCollider2D box)
            {
                box.size = data.BoxSize;
                box.offset = data.BoxOffset;
            }
            else if (data.IsCircle && col is CircleCollider2D circle)
            {
                circle.radius = data.CircleRadius;
            }
            else if (data.IsCapsule && col is CapsuleCollider2D capsule)
            {
                capsule.size = data.CapsuleSize;
            }

            col.transform.localScale = data.TransformScale;

            UpdateColliderDebug(col, data);
        }

        private static void UpdateColliderDebug(Collider2D col, ColliderOriginalData data)
        {
            _debugColliderName = col != null ? col.name : string.Empty;

            if (data.IsBox && col is BoxCollider2D box)
            {
                _debugColliderType = "BoxCollider2D";
                _debugOriginalSize = data.BoxSize;
                _debugCurrentSize = box.size;
                _debugOriginalRadius = 0f;
                _debugCurrentRadius = 0f;
            }
            else if (data.IsCircle && col is CircleCollider2D circle)
            {
                _debugColliderType = "CircleCollider2D";
                _debugOriginalRadius = data.CircleRadius;
                _debugCurrentRadius = circle.radius;
                _debugOriginalSize = Vector2.zero;
                _debugCurrentSize = Vector2.zero;
            }
            else if (data.IsCapsule && col is CapsuleCollider2D capsule)
            {
                _debugColliderType = "CapsuleCollider2D";
                _debugOriginalSize = data.CapsuleSize;
                _debugCurrentSize = capsule.size;
                _debugOriginalRadius = 0f;
                _debugCurrentRadius = 0f;
            }
            else
            {
                _debugColliderType = col != null ? col.GetType().Name : string.Empty;
                _debugOriginalSize = data.TransformScale;
                _debugCurrentSize = col != null ? (Vector2)col.transform.localScale : Vector2.zero;
                _debugOriginalRadius = 0f;
                _debugCurrentRadius = 0f;
            }
        }

        // ---------------------------------------------------------------------
        // HUD
        // ---------------------------------------------------------------------

        private void OnGUI()
        {
            if (!_showHud)
            {
                return;
            }

            GUIStyle style = new GUIStyle(GUI.skin.label)
            {
                fontSize = 18
            };
            style.normal.textColor = Color.yellow;

            int x = 20;
            int y = 20;
            int lineHeight = 22;

            GUI.Label(new Rect(x, y, 350, lineHeight),
                $"DamageHack (F5): {(DamageHackEnabled ? "ON" : "OFF")}", style);
            y += lineHeight;

            GUI.Label(new Rect(x, y, 350, lineHeight),
                $"HitboxHack (F6): {(HitboxHackEnabled ? "ON" : "OFF")}", style);
            y += lineHeight;

            // Live damage values for every player attack dealer
            var player = Player.i;
            if (player != null)
            {
                foreach (var dealer in EnumeratePlayerAttackDealers())
                {
                    if (dealer == null)
                    {
                        continue;
                    }

                    float baseDamage = 0f;
                    float currentDamage = 0f;

                    try
                    {
                        baseDamage = ReadDealerBaseValue(dealer);
                    }
                    catch
                    {
                        // ignore, leave as 0
                    }

                    try
                    {
                        currentDamage = dealer.FinalValue;
                    }
                    catch
                    {
                        currentDamage = baseDamage;
                    }

                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Dealer: {dealer.name}", style);
                    y += lineHeight;

                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Base Damage (live): {baseDamage:F2}", style);
                    y += lineHeight;

                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Current Damage (FinalValue): {currentDamage:F2}", style);
                    y += lineHeight;
                }
            }

            // Detailed debug for last processed damage dealer
            if (!string.IsNullOrEmpty(_debugAttackDealerName))
            {
                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Dealer: {_debugAttackDealerName}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] BaseValue cached: {_debugAttackBaseValue:F2}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Boost norm: {_debugDamageBoostNormalized:F3}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Multiplier applied: {_debugDamageMultiplierApplied:F3}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Target value: {_debugDamageTargetValue:F2}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Provider? {_debugDamageHasProvider}, UsedProvider={_debugDamageUsedProvider}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Provider: {_debugDamageProviderBefore:F2} -> {_debugDamageProviderAfter:F2}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] Field used={_debugDamageUsedField}, value: {_debugDamageFieldBefore:F2} -> {_debugDamageFieldAfter:F2}", style);
                y += lineHeight;

                GUI.Label(new Rect(x, y, 450, lineHeight),
                    $"[Dbg] FinalValue: {_debugDamageFinalBefore:F2} -> {_debugDamageFinalAfter:F2}", style);
                y += lineHeight;

                if (!string.IsNullOrEmpty(_debugDamageLastError))
                {
                    GUI.Label(new Rect(x, y, 600, lineHeight),
                        $"[Dbg] Last error: {_debugDamageLastError}", style);
                    y += lineHeight;
                }
            }

            // Live melee cooldown, animator speed, and input state
            if (player != null)
            {
                bool attackPressed = false;
                try
                {
                    attackPressed = player.AttackPressed;
                }
                catch
                {
                    // ignore
                }

                GUI.Label(new Rect(x, y, 400, lineHeight),
                    $"AttackPressed (live): {attackPressed}", style);
                y += lineHeight;

                float liveCd = player.meleeAttackCooldownTimer;
                GUI.Label(new Rect(x, y, 400, lineHeight),
                    $"Melee CD (live): {liveCd:F3}", style);
                y += lineHeight;

                var anim = player.animator;
                if (anim != null)
                {
                    float liveAnimSpeed = anim.speed;
                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Anim speed (live): {liveAnimSpeed:F2}", style);
                    y += lineHeight;
                }
            }

            // Collider info still reflects actual collider component values
            if (!string.IsNullOrEmpty(_debugColliderName))
            {
                GUI.Label(new Rect(x, y, 400, lineHeight),
                    $"Collider: {_debugColliderName} ({_debugColliderType})", style);
                y += lineHeight;

                if (_debugOriginalRadius > 0f || _debugCurrentRadius > 0f)
                {
                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Radius: {_debugOriginalRadius:F2} -> {_debugCurrentRadius:F2}", style);
                    y += lineHeight;
                }
                else
                {
                    GUI.Label(new Rect(x, y, 400, lineHeight),
                        $"Size: {_debugOriginalSize} -> {_debugCurrentSize}", style);
                    y += lineHeight;
                }
            }
        }
    }
}
