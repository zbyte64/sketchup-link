Feature: Model Mutation Fuzzing
  As a developer I want to mutate the SketchUp model in various ways
  and verify that the live sync pipeline handles each mutation correctly.

  Background:
    Given the Ruby mock server is running
    And the test model is available via the socket

  Scenario: Add a face via mutation
    When I create a new face in SketchUp
    Then all materials are created in the import
    And all mesh geometry is imported
    And a screenshot is captured

  Scenario: Move a group via mutation
    When I move the FurnitureGroup in SketchUp
    Then the FurnitureGroup contains its child entities
    And a screenshot is captured

  Scenario: Change material color via mutation
    When I change the Red material color in SketchUp
    Then the Red material diffuse color matches the expected sRGB-to-linear conversion
    And a screenshot is captured

  Scenario: Rapid stress mutation sequence
    When I apply a stress mutation sequence
    Then all mesh geometry is imported
    And a screenshot is captured
