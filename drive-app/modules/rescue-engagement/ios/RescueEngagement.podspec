Pod::Spec.new do |s|
  s.name           = 'RescueEngagement'
  s.version        = '1.0.0'
  s.summary        = 'Rescue Live Activity + widget data bridge'
  s.description    = 'ActivityKit start/update/end and shared widget data for the Rescue concept'
  s.author         = ''
  s.license        = 'UNLICENSED'
  s.homepage       = 'https://miles.bolls.dev'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "**/*.{h,m,swift}"
end
