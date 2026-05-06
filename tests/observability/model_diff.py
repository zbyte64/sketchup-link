"""
ModelDiffer — Deep comparison of two model JSON snapshots.

Reports added/removed/changed entities, material diffs, layer diffs,
component definition diffs, and transform diffs.

Output: structured diff dict that can be serialized to JSON.
"""

import copy


class ModelDiffer:
    """Compare two model JSON snapshots and produce a structured diff.

    Usage:
        differ = ModelDiffer()
        diff = differ.compare(baseline_json, after_json)
    """

    def compare(self, baseline, after):
        """Deep-compare two model JSON dicts.

        Args:
            baseline: dict — the pre-mutation model snapshot.
            after: dict — the post-mutation model snapshot.

        Returns:
            dict with keys:
                top_level: dict of top-level key diffs.
                entities: list of individual entity diffs.
                materials: list of material diffs.
                layers: list of layer diffs.
                component_definitions: list of component definition diffs.
                summary: dict with counts of changes.
        """
        result = {
            "top_level": self._diff_top_level(baseline, after),
            "entities": self._diff_entities(
                baseline.get("entities", []),
                after.get("entities", []),
            ),
            "materials": self._diff_materials(
                baseline.get("materials", []),
                after.get("materials", []),
            ),
            "layers": self._diff_layers(
                baseline.get("layers", []),
                after.get("layers", []),
            ),
            "component_definitions": self._diff_component_definitions(
                baseline.get("component_definitions", {}),
                after.get("component_definitions", {}),
            ),
        }

        result["summary"] = {
            "entities_added": sum(1 for e in result["entities"] if e["_change"] == "added"),
            "entities_removed": sum(1 for e in result["entities"] if e["_change"] == "removed"),
            "entities_changed": sum(1 for e in result["entities"] if e["_change"] == "changed"),
            "materials_added": sum(1 for m in result["materials"] if m["_change"] == "added"),
            "materials_removed": sum(1 for m in result["materials"] if m["_change"] == "removed"),
            "materials_changed": sum(1 for m in result["materials"] if m["_change"] == "changed"),
            "layers_changed": sum(1 for l in result["layers"] if l["_change"] == "changed"),
            "definitions_changed": sum(1 for d in result["component_definitions"] if d["_change"] == "changed"),
        }

        return result

    # ------------------------------------------------------------------
    # Top-level keys
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_top_level(baseline, after):
        """Diff top-level keys that are not entities/materials/layers/defs."""
        scalar_keys = {"model_guid", "title", "path"}
        diffs = {}
        for key in scalar_keys:
            bv = baseline.get(key)
            av = after.get(key)
            if bv != av:
                diffs[key] = {"before": bv, "after": av}
        return diffs

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------

    def _diff_entities(self, baseline_list, after_list):
        """Diff entities by persistent_id."""
        baseline_by_pid = {e.get("persistent_id"): e for e in baseline_list if e.get("persistent_id")}
        after_by_pid = {e.get("persistent_id"): e for e in after_list if e.get("persistent_id")}

        # Handle entities without persistent_id
        baseline_no_pid = [e for e in baseline_list if not e.get("persistent_id")]
        after_no_pid = [e for e in after_list if not e.get("persistent_id")]

        diffs = []

        # Removed entities
        for pid, entity in baseline_by_pid.items():
            if pid not in after_by_pid:
                diffs.append({
                    "_change": "removed",
                    "persistent_id": pid,
                    "type": entity.get("type"),
                    "name": entity.get("name"),
                })

        # Added entities
        for pid, entity in after_by_pid.items():
            if pid not in baseline_by_pid:
                diffs.append({
                    "_change": "added",
                    "persistent_id": pid,
                    "type": entity.get("type"),
                    "name": entity.get("name"),
                })

        # Changed entities
        for pid in baseline_by_pid:
            if pid in after_by_pid:
                be = baseline_by_pid[pid]
                ae = after_by_pid[pid]
                changed_fields = {}
                for key in ("type", "name", "layer", "material", "back_material",
                            "hidden", "definition_name"):
                    bv = be.get(key)
                    av = ae.get(key)
                    if bv != av:
                        changed_fields[key] = {"before": bv, "after": av}
                # Check transform
                btrans = be.get("transformation")
                atrans = ae.get("transformation")
                if btrans != atrans:
                    changed_fields["transformation"] = {
                        "before": btrans,
                        "after": atrans,
                    }
                # Check sub-entities for groups
                bchildren = be.get("entities", [])
                achildren = ae.get("entities", [])
                if self._entity_list_len(bchildren) != self._entity_list_len(achildren):
                    changed_fields["entities"] = {
                        "before": f"{self._entity_list_len(bchildren)} children",
                        "after": f"{self._entity_list_len(achildren)} children",
                    }

                # Check vertex/triangle changes for faces
                for key in ("vertices", "triangles", "uvs"):
                    bv = be.get(key)
                    av = ae.get(key)
                    if bv is not None and av is not None and bv != av:
                        changed_fields[key] = {"changed": True}

                if changed_fields:
                    diffs.append({
                        "_change": "changed",
                        "persistent_id": pid,
                        "type": ae.get("type", be.get("type")),
                        "name": ae.get("name", be.get("name")),
                        "fields": changed_fields,
                    })

        return diffs

    @staticmethod
    def _entity_list_len(entities):
        """Return len if entities is a list, else 0."""
        if isinstance(entities, list):
            return len(entities)
        return 0

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_materials(baseline_list, after_list):
        """Diff materials by name."""
        baseline_by_name = {m.get("name"): m for m in baseline_list if m.get("name")}
        after_by_name = {m.get("name"): m for m in after_list if m.get("name")}

        diffs = []

        # Removed
        for name in baseline_by_name:
            if name not in after_by_name:
                diffs.append({
                    "_change": "removed",
                    "name": name,
                })

        # Added
        for name in after_by_name:
            if name not in baseline_by_name:
                diffs.append({
                    "_change": "added",
                    "name": name,
                    "color": after_by_name[name].get("color"),
                    "opacity": after_by_name[name].get("opacity"),
                })

        # Changed
        for name in baseline_by_name:
            if name in after_by_name:
                bm = baseline_by_name[name]
                am = after_by_name[name]
                changed_fields = {}
                if bm.get("color") != am.get("color"):
                    changed_fields["color"] = {"before": bm.get("color"), "after": am.get("color")}
                if bm.get("opacity") != am.get("opacity"):
                    changed_fields["opacity"] = {"before": bm.get("opacity"), "after": am.get("opacity")}
                if changed_fields:
                    diffs.append({
                        "_change": "changed",
                        "name": name,
                        "fields": changed_fields,
                    })

        return diffs

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_layers(baseline_list, after_list):
        """Diff layers by name."""
        baseline_by_name = {l.get("name"): l for l in baseline_list if l.get("name")}
        after_by_name = {l.get("name"): l for l in after_list if l.get("name")}

        diffs = []

        for name in baseline_by_name:
            if name in after_by_name:
                bl = baseline_by_name[name]
                al = after_by_name[name]
                changed_fields = {}
                if bl.get("visible") != al.get("visible"):
                    changed_fields["visible"] = {"before": bl.get("visible"), "after": al.get("visible")}
                if changed_fields:
                    diffs.append({
                        "_change": "changed",
                        "name": name,
                        "fields": changed_fields,
                    })
            else:
                diffs.append({
                    "_change": "removed",
                    "name": name,
                })

        for name in after_by_name:
            if name not in baseline_by_name:
                diffs.append({
                    "_change": "added",
                    "name": name,
                    "visible": after_by_name[name].get("visible"),
                })

        return diffs

    # ------------------------------------------------------------------
    # Component definitions
    # ------------------------------------------------------------------

    @staticmethod
    def _diff_component_definitions(baseline_dict, after_dict):
        """Diff component definitions by name."""
        diffs = []
        for name in baseline_dict:
            if name in after_dict:
                bd = baseline_dict[name]
                ad = after_dict[name]
                changed_fields = {}
                if bd.get("num_instances") != ad.get("num_instances"):
                    changed_fields["num_instances"] = {"before": bd.get("num_instances"),
                                                       "after": ad.get("num_instances")}
                if bd.get("num_used_instances") != ad.get("num_used_instances"):
                    changed_fields["num_used_instances"] = {"before": bd.get("num_used_instances"),
                                                            "after": ad.get("num_used_instances")}
                if len(bd.get("entities", [])) != len(ad.get("entities", [])):
                    changed_fields["entity_count"] = {
                        "before": len(bd.get("entities", [])),
                        "after": len(ad.get("entities", [])),
                    }
                if changed_fields:
                    diffs.append({
                        "_change": "changed",
                        "name": name,
                        "fields": changed_fields,
                    })
            else:
                diffs.append({
                    "_change": "removed",
                    "name": name,
                })

        for name in after_dict:
            if name not in baseline_dict:
                diffs.append({
                    "_change": "added",
                    "name": name,
                    "entity_count": len(after_dict[name].get("entities", [])),
                })

        return diffs
