"""
Voices registry.

A reader voice is the institutional role from which the policy is read.
The voice scopes the LLM's interpretation during decomposition,
deduplication, refinement, and (for the narrative substrate) Map binding.

This module is the single source of truth for voice registrations. Both
the CLI (`build_dag.py`) and the study harness (`harness/run_study.py`)
import VOICES from here.

To add a new voice (e.g., for Policy 3 in the comparison study):

    1. Add a classmethod or factory in rulekit/builder.py:ReaderVoice
       returning a ReaderVoice instance with the role text.
    2. Register it here in the VOICES dict with a stable key.
    3. Reference the key in determinations YAML or in policy_config.yaml.
"""

from rulekit.build.extract import ReaderVoice


VOICES = {
    "pa": ReaderVoice.pa_reviewer,
    "fcba": ReaderVoice.fcba_reviewer,
    # Add Policy 3 voice here when the policy is selected, e.g.:
    # "policy3": ReaderVoice.policy3_reviewer,
}
