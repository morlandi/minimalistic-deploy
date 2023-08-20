from dataclasses import dataclass, field, asdict
from typing import List, Dict


@dataclass
class Action:
    title: str = ''
    type: str = ''
    become: bool = False
    become_user: str = ''
    timeout: int = 0
    wrap_bash: bool = True
    when: str = ''
    register: str = ''
    items: List[str] = field(default_factory=list)
    extra: Dict = field(default_factory = lambda: ({}))

    # The following works but is not required any more
    # @classmethod
    # def from_dict(cls, env):
    #     """
    #     Build the dataclass collecting all nexpected params, if any, in a separate  "extra" dict.
    #     Adapted from: [How does one ignore extra arguments passed to a dataclass?](https://stackoverflow.com/questions/54678337/how-does-one-ignore-extra-arguments-passed-to-a-dataclass)
    #     """
    #     cls_parameters = inspect.signature(cls).parameters
    #     extra = {
    #         k: v for k, v in env.items()
    #         if k not in cls_parameters
    #     }
    #     kwargs = {
    #         k: v for k, v in env.items()
    #         if k in cls_parameters
    #     }
    #     return cls(**kwargs, extra=extra)

    def __str__(self):
        return str(self.title)

    def __repr__(self):
        return "Action<%s>" % json.dumps(asdict(self), indent=4)
