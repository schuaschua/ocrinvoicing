"""Story 2.4, AD-10: `PURCHASING_ADAPTER` picks the purchasing adapter in one factory;
`sim` (the default) is the simulation, any other value stops the app naming the
setting."""

import pytest
from sqlalchemy import create_engine

from invoicing.adapters.purchasing_factory import PURCHASING_ADAPTERS, purchasing_port
from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter


def test_story_2_4_the_factory_builds_the_simulation_and_refuses_others() -> None:
    assert PURCHASING_ADAPTERS == ("sim",)
    engine = create_engine("postgresql+psycopg://")
    try:
        assert isinstance(purchasing_port("sim", engine), PurchasingSimAdapter)
        with pytest.raises(ValueError, match="PURCHASING_ADAPTER must be one of: sim"):
            purchasing_port("real", engine)
    finally:
        engine.dispose()
