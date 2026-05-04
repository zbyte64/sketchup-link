# Golden JSON Test Fixture

`test_model.json` is the canonical model snapshot used by
`test_blender_import.py` to validate the full JSON → Blender import pipeline.

## Model Structure

The golden JSON matches the structure produced by `tests/integration/factories.rb`:

|Type|Count|Details|
|---|---|---|
|Faces|2|Face 0: material="Red", no back_material. Face 1: back_material="Blue", no material|
|Edges|1|No material, layer="Layer0"|
|Groups|1|"FurnitureGroup", layer="Furniture", identity transform, 1 face + 1 edge|
|ComponentInstances|1|definition_name="Chair", layer="Furniture", identity transform|
|Materials|2|Red(r=220,g=20,b=20,a=255), Blue(r=20,g=20,b=200,a=255)|
|Layers|3|Layer0(visible), Furniture(visible), Hidden(invisible)|
|ComponentDefinitions|1|Chair — 2 faces, num_instances=1, num_used_instances=1|

## Regeneration

### From the Ruby test factories (no SketchUp needed)

```bash
cd shared/project/ext/sketchup-link
ruby -e '
require_relative "tests/integration/factories"
require "json"
File.write("tests/integration/golden/test_model.json",
           JSON.pretty_generate(Factories.test_model))
'
```

### From a real SketchUp model (requires Docker VM)

1. Start the Docker Windows 11 VM: `docker compose -f ../../integration/compose.yml up -d`
2. RDP into the VM (port 3389, credentials: Docker / admin)
3. Open or create the test model in SketchUp Pro
4. In SketchUp, go to **Plugins → SketchUp Link: Save Model JSON**
5. The JSON file is written to `/shared/model_snapshot.json` on the host
6. Copy to the golden directory: `cp /shared/model_snapshot.json tests/integration/golden/test_model.json`
