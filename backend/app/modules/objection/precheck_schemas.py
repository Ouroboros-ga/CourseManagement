import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrecheckEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["APPLICATION", "ATTENDANCE", "PROOF"]
    file_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")
    page: int | None = Field(default=None, ge=1, le=200)
    quote: str | None = Field(default=None, max_length=400)
    observation: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def proof_reference(self):
        if self.source == "PROOF":
            if self.file_id is None or int(self.file_id) >= 2**63:
                raise ValueError("证明材料必须使用本次申诉的文件编号")
        elif self.file_id is not None or self.page is not None:
            raise ValueError("仅证明材料可以引用文件及页码")
        return self


class PrecheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recommendation: Literal["SUPPORT", "NEEDS_INFORMATION", "NEEDS_VERIFICATION"]
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[PrecheckEvidence] = Field(max_length=20)
    questions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=10
    )

    @model_validator(mode="after")
    def evidence_uses_file_references(self):
        # Advice cites bound file IDs, never copies temporary download credentials.
        # Cloud-side request/history redaction is still a separate activation gate.
        if re.search(
            r"https?://|/files/\d+/download|[?&](?:sig|signature|x-oss-signature|x-amz-signature)=",
            self.model_dump_json(),
            re.IGNORECASE,
        ):
            raise ValueError("预审意见仅使用材料编号引用，不保存网址或签名下载链接")
        return self
