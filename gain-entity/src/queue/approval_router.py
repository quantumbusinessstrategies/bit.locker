from __future__ import annotations


class ApprovalRouter:
    ACTION_TO_STATUS = {
        "Approve": "Approved",
        "Reject": "Rejected",
        "Later": "Later",
        "Connect Needed": "Connect Needed",
        "Claim Submitted": "Submitted",
        "Ready to Accept": "Ready to Accept",
        "Accepted": "Accepted",
        "Received/Paid": "Received/Paid",
        "Dead End": "Dead End",
    }

    @classmethod
    def status_for_action(cls, action: str) -> str:
        return cls.ACTION_TO_STATUS[action]

    @classmethod
    def actions(cls) -> list[str]:
        return list(cls.ACTION_TO_STATUS.keys())
