"""Story 2.2: the stage queues and their poison queues (AD-2)."""

from invoicing.domain.status import Stage
from invoicing.ports.queue import POISON_QUEUES, STAGE_QUEUES


def test_story_2_2_each_stage_has_its_queue_and_the_hosts_poison_queue() -> None:
    assert {stage: q.value for stage, q in STAGE_QUEUES.items()} == {
        Stage.QUALITY: "q-quality",
        Stage.EXTRACT: "q-extract",
        Stage.VALIDATE: "q-validate",
        Stage.POST: "q-post",
    }
    # The Functions host moves a message to `<queue>-poison` after maxDequeueCount.
    assert {stage: q.value for stage, q in POISON_QUEUES.items()} == {
        stage: f"{q.value}-poison" for stage, q in STAGE_QUEUES.items()
    }
