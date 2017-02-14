# coding: utf8
from __future__ import unicode_literals, print_function, division
from collections import defaultdict, Counter
from itertools import chain
import os
import sys
import subprocess
import re

from termcolor import colored
from clldutils.clilib import command, ParserError
from clldutils.misc import slug
from clldutils.markup import Table
from clldutils.path import Path

from pyglottolog.languoids import Level, Glottocode, Languoid
from pyglottolog import fts
from pyglottolog import lff
from pyglottolog.monster import compile
import pyglottolog.iso
from pyglottolog.util import message


@command()
def isobib(args):
    """
    Update iso6393.bib - the file of references for ISO 639-3 change requests.
    """
    pyglottolog.iso.bibtex(args.repos, args.log)


def existing_lang(args):
    if not args.args:
        raise ParserError('No languoid specified')
    lang = args.repos.languoid(args.args[0])
    if not lang:
        raise ParserError('Invalid languoid spec')
    return lang


def cprint(text, color=None, attrs=None):
    print(colored(text, color, attrs=attrs or []).encode('utf8'))


@command()
def show(args):
    lang = existing_lang(args)
    print()
    cprint('Glottolog languoid {0}'.format(lang.id), attrs=['bold', 'underline'])
    print()
    cprint('Classification:', attrs=['bold', 'underline'])
    args.repos.ascii_tree(lang, maxlevel=1)
    print()
    cprint('Info:', attrs=['bold', 'underline'])
    cprint('Path: {0}'.format(lang.fname), 'green', attrs=['bold'])
    for line in lang.cfg.write_string().split('\n'):
        if not line.startswith('#'):
            cprint(line, None, attrs=['bold'] if line.startswith('[') else [])


@command()
def edit(args):
    lang = existing_lang(args)
    if sys.platform.startswith('os2'):  # pragma: no cover
        cmd = ['open']
    elif sys.platform.startswith('linux'):
        cmd = ['xdg-open']
    elif sys.platform.startswith('win'):  # pragma: no cover
        cmd = []
    else:  # pragma: no cover
        print(lang.fname)
        return
    cmd.append(lang.fname.as_posix())
    subprocess.call(cmd)


@command()
def create(args):
    """Create a new languoid directory for a languoid specified by name and level.

    glottolog create <parent> <name> <level>
    """
    assert args.args[2] in ['family', 'language', 'dialect']
    parent = args.repos.languoid(args.args[0]) or None
    lang = Languoid.from_name_id_level(
        args.args[1],
        args.repos.glottocodes.new(args.args[1]),
        getattr(Level, args.args[2]),
        **dict(prop.split('=') for prop in args.args[3:]))

    outdir = parent.dir if parent else args.repos.languoids_path('tree')
    print("Info written to %s" % lang.write_info(outdir=outdir))


@command()
def bib(args):
    """Compile the monster bibfile from the BibTeX files listed in references/BIBFILES.ini

    glottolog monster
    """
    compile(args.repos, args.log, rebuild=bool(args.args))


@command()
def tree(args):
    """Print the classification tree starting at a specific Glottocode

    glottolog tree GLOTTOCODE
    """
    start = existing_lang(args)
    maxlevel = None
    if len(args.args) > 1:
        try:
            maxlevel = int(args.args[1])
        except:
            maxlevel = getattr(Level, args.args[1], None)
    args.repos.ascii_tree(start, maxlevel=maxlevel)


@command()
def newick(args):
    print(args.repos.newick_tree(args.args[0]))


@command()
def index(args):
    """Create an index page listing and linking to all languoids of a specified level.

    glottolog index (family|language|dialect|all)
    """
    def make_index(level, languoids, repos):
        fname = dict(
            language='languages', family='families', dialect='dialects')[level.name]
        links = defaultdict(dict)
        for lang in languoids:
            label = '{0.name} [{0.id}]'.format(lang)
            if lang.iso:
                label += '[%s]' % lang.iso
            links[slug(lang.name)[0]][label] = \
                lang.fname.relative_to(repos.languoids_path())

        with repos.languoids_path(fname + '.md').open('w', encoding='utf8') as fp:
            fp.write('## %s\n\n' % fname.capitalize())
            fp.write(' '.join(
                '[-%s-](%s_%s.md)' % (i.upper(), fname, i) for i in sorted(links.keys())))
            fp.write('\n')

        for i, langs in links.items():
            with repos.languoids_path(
                    '%s_%s.md' % (fname, i)).open('w', encoding='utf8') as fp:
                for label in sorted(langs.keys()):
                    fp.write('- [%s](%s)\n' % (label, langs[label]))

    langs = list(args.repos.languoids())
    for level in Level():
        if not args.args or args.args[0] == level.name:
            make_index(level, [l for l in langs if l.level == level], args.repos)


@command()
def check(args):
    def error(obj, msg):
        args.log.error(message(obj, msg))

    def warn(obj, msg):
        args.log.warn(message(obj, msg))

    def info(obj, msg):
        args.log.info(message(obj, msg))

    what = args.args[0] if args.args else 'all'

    if what in ['all', 'refs']:
        for bibfile in args.repos.bibfiles:
            bibfile.check(args.log)

    if what not in ['all', 'tree']:
        return

    iso = args.repos.iso
    args.log.info('checking ISO codes against %s' % iso)
    args.log.info('checking tree at %s' % args.repos)
    by_level = Counter()
    by_category = Counter()
    iso_in_gl, languoids, iso_splits = {}, {}, []
    names = defaultdict(set)

    for lang in args.repos.languoids():
        # duplicate glottocodes:
        if lang.id in languoids:
            error(
                lang.id,
                'duplicate glottocode\n{0}\n{1}'.format(languoids[lang.id].dir, lang.dir))
        languoids[lang.id] = lang

    for lang in languoids.values():
        ancestors = lang.ancestors_from_nodemap(languoids)
        children = lang.children_from_nodemap(languoids)

        assert isinstance(lang.countries, list)
        assert isinstance(lang.macroareas, list)

        names[lang.name].add(lang)
        by_level.update([lang.level.name])
        if lang.level == Level.language:
            by_category.update([lang.category])

        if iso and lang.iso:
            if lang.iso not in iso:
                warn(lang, 'invalid ISO-639-3 code [%s]' % lang.iso)
            else:
                isocode = iso[lang.iso]
                if lang.iso in iso_in_gl:
                    error(isocode,
                          'duplicate: {0}, {1}'.format(iso_in_gl[lang.iso].id, lang.id))
                iso_in_gl[lang.iso] = lang
                if isocode.is_retired and lang.category != 'Bookkeeping':
                    if isocode.type == 'Retirement/split':
                        iso_splits.append(lang)
                    else:
                        msg = repr(isocode)
                        level = info
                        if len(isocode.change_to) == 1:
                            level = warn
                            msg += ' changed to [%s]' % isocode.change_to[0].code
                        level(lang, msg)

        if not lang.id.startswith('unun9') and lang.id not in args.repos.glottocodes:
            error(lang, 'unregistered glottocode')
        for attr in ['level', 'name']:
            if not getattr(lang, attr):
                error(lang, 'missing %s' % attr)
        if lang.level == Level.language:
            parent = ancestors[-1] if ancestors else None
            if parent and parent.level != Level.family:
                error(lang, 'invalid nesting of language under {0}'.format(parent.level))
            for child in children:
                if child.level != Level.dialect:
                    error(child,
                          'invalid nesting of {0} under language'.format(child.level))
        elif lang.level == Level.family:
            for d in lang.dir.iterdir():
                if d.is_dir():
                    break
            else:
                error(lang, 'family without children')

    if iso:
        changed_to = set(chain(*[code.change_to for code in iso.retirements]))
        for code in sorted(iso.languages):
            if code.type == 'Individual/Living':
                if code not in changed_to:
                    if code.code not in iso_in_gl:
                        info(repr(code), 'missing')
        for lang in iso_splits:
            isocode = iso[lang.iso]
            missing = [s.code for s in isocode.change_to if s.code not in iso_in_gl]
            if missing:
                warn(lang, '{0} missing new codes: {1}'.format(
                    repr(isocode), ', '.join(missing)))

    for name, gcs in sorted(names.items()):
        if len(gcs) > 1:
            # duplicate names:
            method = error
            if len([1 for n in gcs if n.level != Level.dialect]) <= 1:
                # at most one of the languoids is not a dialect, just warn
                method = warn
            if len([1 for n in gcs
                    if (not n.lineage) or (n.lineage[0][1] != 'book1242')]) <= 1:
                # at most one of the languoids is not in bookkeping, just warn
                method = warn
            method(name, 'duplicate name: {0}'.format(', '.join(sorted(
                ['{0} <{1}>'.format(n.id, n.level.name[0]) for n in gcs]))))

    def log_counter(counter, name):
        msg = [name + ':']
        maxl = max([len(k) for k in counter.keys()]) + 1
        for k, l in counter.most_common():
            msg.append(('{0:<%s} {1:>8,}' % maxl).format(k + ':', l))
        msg.append(('{0:<%s} {1:>8,}' % maxl).format('', sum(list(counter.values()))))
        print('\n'.join(msg))

    log_counter(by_level, 'Languoids by level')
    log_counter(by_category, 'Languages by category')
    return by_level


@command()
def metadata(args):
    ops = defaultdict(Counter)

    for l in args.repos.languoids():
        for sec in l.cfg:
            for opt in l.cfg[sec]:
                if l.cfg.get(sec, opt):
                    ops[sec].update([opt])

    t = Table('section', 'option', 'count')
    for section, options in ops.items():
        t.append([section, '', 0.0])
        for k, n in options.most_common():
            t.append(['', k, float(n)])
    print(t.render(condensed=False, floatfmt=',.0f'))


@command()
def refsearch(args):
    """
    Search Glottolog references

    glottolog ftssearch QUERY

    E.g.:
    - glottolog ftssearch "Izi provider:hh"
    - glottolog ftssearch "author:Haspelmath provider:wals"
    """
    count, results = fts.search(args.repos, args.args[0])
    table = Table('ID', 'Author', 'Year', 'Title')
    for res in results:
        table.append([res.id, res.author, res.year, res.title])
    print(table.render(tablefmt='simple'))
    print('({} matches)'.format(count))


@command()
def refindex(args):
    """
    Index all bib files for use with the whoosh search engine.
    """
    return fts.build_index(args.repos, args.log)


@command()
def langsearch(args):
    """
    Search Glottolog languoids

    """
    def highlight(text):
        pre, rem = text.split('[[', 1)
        hl, post = rem.split(']]', 1)
        return pre + colored(hl, 'red', attrs=['bold']) + post + '\n'

    count, results = fts.search_langs(args.repos, args.args[0])
    cwd = os.getcwd()
    print('{} matches'.format(count))
    for res in results:
        try:
            p = Path(res.fname).relative_to(Path(cwd))
        except ValueError:
            p = res.fname
        cprint('{0.name} [{0.id}] {0.level}'.format(res), None, attrs=['bold'])
        cprint(p, 'green')
        print(highlight(res.highlights) if res.highlights else '')
    print('{} matches'.format(count))


@command()
def langindex(args):
    """
    Index all bib files for use with the whoosh search engine.
    """
    return fts.build_langs_index(args.repos, args.log)


@command()
def tree2lff(args):
    """Create lff.txt and dff.txt from the current languoid tree.

    glottolog tree2lff
    """
    lff.tree2lff(args.repos, args.log)


@command()
def lff2tree(args):
    """Recreate tree from lff.txt and dff.txt

    glottolog lff2tree [test]
    """
    try:
        lff.lff2tree(args.repos, args.log)
    except ValueError:
        print("""
Something went wrong! Roll back inconsistent state running

    rm -rf languoids
    git checkout languoids
""")
        raise

    if args.args and args.args[0] == 'test':  # pragma: no cover
        print("""
You can run

    diff -rbB build/tree/ languoids/tree/

to inspect the changes in the directory tree.
""")
    else:
        print("""
Run

    git status

to inspect changes in the directory tree.
You can run

    diff -rbB build/tree/ languoids/tree/

to inspect the changes in detail.

- To discard changes run

    git checkout languoids/tree

- To commit and push changes, run

    git add -A languoids/tree/...

  for any newly created nodes listed under

# Untracked files:
#   (use "git add <file>..." to include in what will be committed)
#
#	languoids/tree/...

  followed by

    git commit -a -m"reason for change of classification"
    git push origin
""")


@command()
def classification(args):
    map = {v: k for k, v in args.repos.bibfiles['hh.bib'].glottolog_ref_id_map.items()}
    for lang in args.repos.languoids(maxlevel=Level.language):
        clf = lang.classification_comment
        if clf.check(lang, map):
            lang.write_info(outdir=lang.dir)
