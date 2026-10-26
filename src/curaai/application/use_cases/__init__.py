"""Use-case interactors: workflow only, no business rules (rules live in Ring 1).

    PipelineTrigger      runs on EVERY inbound patient message (no model gate)
      -> ScreenSickMessage     extract symptoms / onset / trend, validate
      -> RequestFollowUp       ask only for what is missing (catalog question)
      -> PrefetchHistory       fixed 3-week chart pull + validated AI lookups
      -> AssembleReviewPacket  build the packet and hand it to ReviewOutputPort
"""

from curaai.application.use_cases.assemble_review_packet import AssembleReviewPacket
from curaai.application.use_cases.pipeline_trigger import PipelineOutcome, PipelineTrigger, TriggerResult
from curaai.application.use_cases.prefetch_history import PrefetchHistory, PrefetchResult
from curaai.application.use_cases.request_follow_up import RequestFollowUp
from curaai.application.use_cases.screen_sick_message import ScreenSickMessage

__all__ = [
    "AssembleReviewPacket", "PipelineOutcome", "PipelineTrigger", "PrefetchHistory",
    "PrefetchResult", "RequestFollowUp", "ScreenSickMessage", "TriggerResult",
]
