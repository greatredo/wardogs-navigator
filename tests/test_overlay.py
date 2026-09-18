import math
import pytest
from wardogs_nav.overlay import project_to_minimap
from wardogs_nav.vision import Fix


@pytest.mark.parametrize('angle,scale',[(0,.35),(90,.15),(-37,.6)])
def test_path_projection_inverts_map_scale_rotation_and_anchor(angle,scale):
    fix=Fix(x=400,y=800,scale=scale,rotation=angle,valid=True)
    # Independent known map motion from a point 20 pixels east / 15 north.
    r=math.radians(angle);dx,dy=20,-15
    point=(400+scale*(math.cos(r)*dx-math.sin(r)*dy),800+scale*(math.sin(r)*dx+math.cos(r)*dy))
    result=project_to_minimap([point],fix,(400,300),(.4,.6))
    assert result[0]==pytest.approx((180,165))
    fix.valid=False
    assert not project_to_minimap([point],fix,(400,300),(.4,.6))
