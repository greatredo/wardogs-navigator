"""Export a standalone source tree and ZIP from an explicit public file list."""
from pathlib import Path
import argparse
import shutil
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
TOP=['.gitignore','.gitattributes','LICENSE','NOTICE','README.md','CONTRIBUTING.md',
     'THIRD_PARTY_NOTICES.md','requirements.txt','build.ps1','main.py','启动导航.cmd']
TOOLS=['copy_licenses.py','export_source.py','make_diagnostic_sample.py',
       'fetch_clean_map.py','prepare_clean_map.py','extract_roads.py','build_map_features.py',
       'publish_map_assets.py','prepare_extra_maps.py','extract_extra_roads.py']
ASSETS=['README.md','maps.json','map-source.json','default_project.json','legacy-road-seed.json',
        'ozeti.png','ozeti-features.npz','sample_minimap.png','wardogs-calculator-LICENSE.txt']
for map_id in ('bakurani','zestafona'):
    ASSETS.extend(f'maps/{map_id}/{name}' for name in ('map.png','features.npz','project.json','source.json','reference-crop.png'))


def public_files():
    paths=[*(Path(p) for p in TOP),*(Path('tools')/p for p in TOOLS),*(Path('assets')/p for p in ASSETS)]
    paths.extend(p.relative_to(ROOT) for p in (ROOT/'wardogs_nav').glob('*.py'))
    paths.extend(p.relative_to(ROOT) for p in (ROOT/'tests').glob('test_*.py'))
    # Community submissions are reviewed data and documentation, not executables.
    community=ROOT/'community'
    if community.is_dir():
        allowed={'.md','.json','.png','.jpg','.jpeg','.webp'}
        paths.extend(p.relative_to(ROOT) for p in community.rglob('*')
                     if p.is_file() and not p.is_symlink() and p.suffix.lower() in allowed
                     and not any(part.startswith('.') for part in p.relative_to(community).parts))
    return sorted(set(paths),key=lambda p:p.as_posix())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='dist/open-source/WardogsNavigator')
    args=parser.parse_args()
    destination=(ROOT/args.output).resolve()
    if not destination.is_relative_to((ROOT/'dist').resolve()):
        parser.error('输出目录必须位于项目 dist 内')
    archive=destination.with_name(destination.name+'-source.zip')
    if destination.exists() or archive.exists():
        parser.error('输出已存在；请选择新的 --output 目录，避免覆盖已有文件或 Git 历史')
    paths=public_files()
    for path in paths:
        if not (ROOT/path).is_file():parser.error(f'缺少公开文件：{path}')
    destination.mkdir(parents=True)
    for path in paths:
        target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/path,target)
    with ZipFile(archive,'x',compression=ZIP_DEFLATED,compresslevel=6) as output:
        for path in paths:output.write(destination/path,(Path(destination.name)/path).as_posix())
    print(f'公开源码：{destination}\n源码压缩包：{archive}\n文件数：{len(paths)}')


if __name__=='__main__':main()
