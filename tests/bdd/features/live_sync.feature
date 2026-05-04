Feature: Live Sync Round Trip
  As a user I want SketchUp model changes to appear live in Blender
  so I can use Blender's rendering and animation tools on my SketchUp models.

  Background:
    Given the Ruby mock server is running
    And the test model is available via the socket

  Scenario: Initial model import
    When I import the model via live sync
    Then all materials are created in the import
    And all mesh geometry is imported
    And component definitions are imported as collections
    And layer visibility is respected
    And a screenshot is captured

  Scenario: Face vertex positions are correct
    When I import the model via live sync
    Then the face vertex positions match the JSON data
    And a screenshot is captured

  Scenario: Material colors are accurate
    When I import the model via live sync
    Then the Red material diffuse color matches the expected sRGB-to-linear conversion
    And the Blue material diffuse color matches the expected sRGB-to-linear conversion
    And a screenshot is captured

  Scenario: Group hierarchy is preserved
    When I import the model via live sync
    Then the FurnitureGroup contains its child entities
    And the FurnitureGroup parent-child hierarchy is correct
    And a screenshot is captured

  Scenario: Component instances reference correct definitions
    When I import the model via live sync
    Then the Chair component instance uses the Chair definition
    And the Chair definition has the correct face count
    And a screenshot is captured
