from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

root=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'dist/WardogsNavigator/licenses'
out.mkdir(parents=True,exist_ok=True)
for package in ['PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','opencv-python-headless','numpy','mss','pyinstaller']:
    dist=distribution(package)
    for file in dist.files or []:
        if any(word in file.name.lower() for word in ('license','copying','notice')) and dist.locate_file(file).is_file():
            destination=out/package/str(file).replace('..','_')
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dist.locate_file(file),destination)
print('Third-party licenses collected')
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copy2(python_license,out/'PYTHON-LICENSE.txt')
shutil.copy2(root/'assets/wardogs-calculator-LICENSE.txt',out/'wardogs-calculator-LICENSE.txt')
