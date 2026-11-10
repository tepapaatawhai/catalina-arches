"""Resolve controlled-list relationship labels when indexing resource instances.

A resource-instance node can carry ``relationshipConcept`` and
``inverseRelationshipConcept`` ids in its config. The editor copies them into
the tile as ``ontologyProperty`` and ``inverseOntologyProperty``. When the
resource is indexed, Arches 8.1 treats any UUID there as a legacy RDM value id
and runs ``Value.objects.get(pk=...)``, which raises ``Value.DoesNotExist`` and
turns the tile save into a 500 for ids that belong to a controlled list.

The replacement looks the id up as a controlled-list item value first, then
falls back to the legacy lookup. If neither knows the id it returns None, which
makes the caller index the raw id string instead of aborting the save.

Remove this once Arches resolves relationship labels from controlled lists.
"""

import logging

logger = logging.getLogger(__name__)


def get_relationship_display_value(self, relationship_valueid):
    from arches.app.models.concept import get_preflabel_from_valueid
    from arches.app.models.models import Value
    from django.utils.translation import get_language

    from arches_controlled_lists.models import ListItemValue

    language = get_language()
    found = ListItemValue.objects.filter(pk=relationship_valueid).first()
    if found is not None:
        siblings = ListItemValue.objects.filter(
            list_item_id=found.list_item_id, valuetype_id="prefLabel"
        )
        match = (
            siblings.filter(language_id=language).first()
            or siblings.filter(language_id=(language or "").split("-")[0]).first()
            or siblings.first()
            or found
        )
        return match.value

    try:
        preflabel = get_preflabel_from_valueid(relationship_valueid, language)
    except Value.DoesNotExist:
        logger.warning(
            "Relationship id %s is neither a controlled-list item value nor a "
            "concept value; indexing it as a plain string.",
            relationship_valueid,
        )
        return None
    return preflabel["value"] if preflabel else None


def apply():
    from arches.app.datatypes import datatypes

    cls = datatypes.ResourceInstanceDataType
    if getattr(cls, "_catalina_relationship_label_patched", False):
        return

    cls.get_relationship_display_value = get_relationship_display_value
    cls._catalina_relationship_label_patched = True
    logger.debug("Applied relationship label patch")
