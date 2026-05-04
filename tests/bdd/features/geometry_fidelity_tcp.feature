Feature: Geometric Fidelity (TCP mode)
  As a user I want geometry imported from SketchUp to be accurate
  so my Blender renders match the original model.

  Background:
    Given SketchUp is serving on TCP

  Scenario: Transform matrix round-trip preserves identity
    When I import the model via live sync
    Then the FurnitureGroup transform is identity
    And a screenshot is captured
    And a wireframe screenshot is captured

  Scenario: Face materials are correctly assigned
    When I import the model via live sync
    Then the front-face material references are correct
    And the back-face material references are correct
    And a screenshot is captured
    And a wireframe screenshot is captured

  Scenario: All entities are present after import
    When I import the model via live sync
    Then the number of imported entities matches the JSON data
    And a screenshot is captured
    And a wireframe screenshot is captured

  Scenario: Hidden layer entities are excluded
    When I import the model via live sync
    Then entities on hidden layers are not imported
    And a screenshot is captured
    And a wireframe screenshot is captured
