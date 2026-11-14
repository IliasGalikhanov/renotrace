"""Assemble readable specification and a local archive of the design package."""
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    docs = sorted((ROOT / 'docs').glob('*.md'))
    header = [
        '# RenoLedger полная спецификация проекта', '',
        'Версия 0.1 · 14 ноября 2026 года', '',
        'Описание продукта, техническое задание, UX, финансовые правила, архитектура, модель данных, API, качество, план разработки и платный пилот.', '',
        'Статус: проектная спецификация. Приложение ещё не реализовано. Цена, спрос, расходы и преимущества требуют проверки. Весь демонстрационный материал синтетический.', '',
        'Этот файл собран из разделов `docs/`. Для редактирования используйте исходные разделы и пересоберите комплект.', '',
        '## Содержание', '',
    ]
    for index, path in enumerate(docs, 1):
        title = path.read_text(encoding='utf-8').splitlines()[0].lstrip('# ')
        header.append(f'{index}. [{title}](docs/{path.name})')
    full = '\n'.join(header) + '\n\n'
    for path in docs:
        source = path.read_text(encoding='utf-8')
        source = source.replace('](../contracts/', '](contracts/').replace('](../fixtures/', '](fixtures/')
        lines, fenced = [], False
        for line in source.splitlines():
            if line.startswith('```'):
                fenced = not fenced
            if not fenced and re.match(r'^#{1,5} ', line):
                line = '#' + line
            lines.append(line)
        full += '\n'.join(lines) + '\n\n'
    (ROOT / 'RENOLEDGER_FULL_SPEC.md').write_text(full, encoding='utf-8')
    paths = [ROOT / 'README.md', ROOT / 'RENOLEDGER_FULL_SPEC.md', *docs,
             *sorted((ROOT / 'contracts').glob('*.json')),
             *sorted((ROOT / 'fixtures').glob('*.json')),
             *sorted((ROOT / 'tools').glob('*.py'))]
    archive = ROOT / 'RenoLedger_Project_Pack.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, 'Archive checksum validation failed'
        assert len(bundle.namelist()) == len(paths)
    print(f'Packaged {len(paths)} files; combined specification {len(full.splitlines())} lines; ZIP {archive.stat().st_size:,} bytes.')


if __name__ == '__main__':
    main()
