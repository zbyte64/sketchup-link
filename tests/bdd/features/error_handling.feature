Feature: Error Handling During Live Sync
  As a user I want sensible error messages when something goes wrong
  so I can diagnose and fix the problem rather than seeing a crash or silent failure.

  Scenario: Connection fails when SketchUp plugin is not running
    Given the SketchUp plugin is not running
    When the Blender plugin attempts to connect
    Then a connection error is raised

  Scenario: Server returns an HTTP error response
    Given a SketchUp mock server returning HTTP 500
    When the Blender plugin fetches the model
    Then an HTTP error is raised

  Scenario: Model JSON is missing required top-level keys
    Given malformed model JSON with only an invalid key
    When the JSON is wrapped in JsonModel
    Then accessing entities returns an empty iterable
    Then accessing materials returns an empty iterable
    Then accessing layers returns an empty iterable

  Scenario: Model contains zero entities
    Given an empty model JSON
    When the JSON is wrapped in JsonModel
    Then all entity iterables are empty
