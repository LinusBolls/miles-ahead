/**
 * Rescue widget + Live Activity native target (compiled by @bacons/apple-targets; on unless APPLE_TARGETS=0).
 *
 * Data hand-off app -> widget uses a shared KEYCHAIN access group, deliberately NOT an App Group: EAS cannot create or
 * link App Group identifiers when it signs with an App Store Connect API key (capability-identifier sync is skipped),
 * whereas every provisioning profile already allows "<TeamID>.*" keychain groups. Keep the group string in sync with
 * app.config.ts (ios.entitlements), RescueShared.swift and modules/rescue-engagement.
 */
/** @type {import('@bacons/apple-targets/app.plugin').Config} */
module.exports = {
  type: "widget",
  name: "RescueWidget",
  displayName: "Rescue",
  bundleIdentifier: ".widget",
  // containerBackground(for: .widget) and the Live Activity UI need iOS 17.
  deploymentTarget: "17.0",
  frameworks: ["SwiftUI", "WidgetKit", "ActivityKit"],
  entitlements: {
    "keychain-access-groups": ["A5X77AGYX4.so.bolls.fuelback.shared"],
  },
};
