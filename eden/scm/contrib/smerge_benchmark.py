# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2.

import csv
import re
import time
from dataclasses import dataclass

from sapling import error, mdiff, registrar, scmutil
from sapling.i18n import _
from sapling.simplemerge import (
    automerge_adjacent_changes,
    automerge_common_changes,
    Merge3Text,
    render_minimized,
    wordmergemode,
)

cmdtable = {}
command = registrar.command(cmdtable)


WHITE_SPACE_PATTERN = re.compile(b"\\s+")


class SmartMerge3Text(Merge3Text):
    """
    SmergeMerge3Text uses vairable automerge algorithms to resolve conflicts.
    """

    def __init__(self, basetext, atext, btext, wordmerge=wordmergemode.disabled):
        Merge3Text.__init__(self, basetext, atext, btext, wordmerge=wordmerge)
        self.automerge_fns.extend(
            [
                automerge_adjacent_changes,
                automerge_common_changes,
            ]
        )


@dataclass
class BenchStats:
    merger_name: str = ""
    changed_files: int = 0
    unresolved_files: int = 0
    unmatched_files: int = 0


@command(
    "debugsmerge",
    [],
    _("[OPTION]... <DEST_FILE> <SRC_FILE> <BASE_FILE>"),
)
def debugsmerge(ui, repo, *args, **opts):
    """
    debug the performance of SmartMerge3Text
    """
    if len(args) != 3:
        raise error.CommandError("debugsmerge", _("invalid arguments"))

    desttext, srctext, basetext = [readfile(p) for p in args]
    m3 = SmartMerge3Text(basetext, desttext, srctext)
    lines = render_mergediff2(m3, b"dest", b"source")[0]
    mergedtext = b"".join(lines)
    ui.fout.write(mergedtext)


@command(
    "sresolve",
    [
        (
            "s",
            "smart",
            None,
            _("use the smart merge for resolving conflicts"),
        ),
        (
            "o",
            "output",
            "/tmp/sresolve.txt",
            _("output file path of the resolved text"),
        ),
    ],
    _("[OPTION]... <FILEPATH> <DEST> <SRC> <BASE>"),
)
def sresolve(ui, repo, *args, **opts):
    """
    sresolve resolves file conficts based on the specified dest, src and base revisions.

    This is for manually verifying the correctness of merge conflict resolution. The input
    arguments order `<FILEPATH> <DEST> <SRC> <BASE>` matches the output of `smerge_bench`
    command.
    """
    if len(args) != 4:
        raise error.CommandError("smerge", _("invalid arguments"))

    filepath = args[0]
    dest, src, base = [scmutil.revsingle(repo, x) for x in args[1:]]

    desttext = repo[dest][filepath].data()
    srctext = repo[src][filepath].data()
    basetext = repo[base][filepath].data()

    if opts.get("smart"):
        m3 = SmartMerge3Text(basetext, desttext, srctext)
    else:
        m3 = Merge3Text(basetext, desttext, srctext)

    mergedtext = b"".join(render_mergediff2(m3, b"dest", b"source")[0])

    if output := opts.get("output"):
        ui.write(f"writing to file: {output}\n")
        with open(output, "wb") as f:
            f.write(mergedtext)
    else:
        ui.fout.write(mergedtext)


@command(
    "smerge_bench",
    [("f", "file", "", _("a file that contains merge commits (csv file)."))],
)
def smerge_bench(ui, repo, *args, **opts):
    path = opts.get("file")
    if path:
        merge_ctxs = get_merge_ctxs_from_file(ui, repo, path)
    else:
        merge_ctxs = get_merge_ctxs_from_repo(ui, repo)
    for m3merger in [SmartMerge3Text, Merge3Text]:
        ui.write(f"\n============== {m3merger.__name__} ==============\n")
        start = time.time()
        bench_stats = BenchStats(m3merger.__name__)

        for i, (p1ctx, p2ctx, basectx, mergectx) in enumerate(merge_ctxs, start=1):
            for filepath in mergectx.files():
                if all(filepath in ctx for ctx in [basectx, p1ctx, p2ctx, mergectx]):
                    merge_file(
                        repo,
                        p1ctx,
                        p2ctx,
                        basectx,
                        mergectx,
                        filepath,
                        m3merger,
                        bench_stats,
                    )

            if i % 100 == 0:
                ui.write(f"{i} {bench_stats}\n")

        ui.write(f"\nSummary: {bench_stats}\n")
        ui.write(f"Execution time: {time.time() - start:.2f} seconds\n")


def get_merge_ctxs_from_repo(ui, repo):
    ui.write("generating merge data from repo ...\n")
    merge_commits = repo.dageval(lambda dag: dag.merges(dag.all()))
    octopus_merges, criss_cross_merges = 0, 0

    ctxs = []
    for i, merge_commit in enumerate(merge_commits, start=1):
        parents = repo.dageval(lambda: parentnames(merge_commit))
        if len(parents) != 2:
            # skip octopus merge
            #    a
            #  / | \
            # b  c  d
            #  \ | /
            #    e
            octopus_merges += 1
            continue

        p1, p2 = parents
        gcas = repo.dageval(lambda: gcaall([p1, p2]))
        if len(gcas) != 1:
            # skip criss cross merge
            #    a
            #   / \
            #  b1  c1
            #  |\ /|
            #  | X |
            #  |/ \|
            #  b2  c2
            criss_cross_merges += 1
            continue

        basectx = repo[gcas[0]]
        p1ctx, p2ctx = repo[p1], repo[p2]
        mergectx = repo[merge_commit]
        ctxs.append((p1ctx, p2ctx, basectx, mergectx))

    ui.write(
        f"len(merge_ctxs)={len(ctxs)}, octopus_merges={octopus_merges}, "
        f"criss_cross_merges={criss_cross_merges}\n"
    )
    return ctxs


def get_merge_ctxs_from_file(ui, repo, filepath):
    def get_merge_commits_from_file(filepath):
        merge_commits = []
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                merge_commits.append(
                    (row["dest_hex"], row["src_hex"], row["newnode_hex"])
                )
        return merge_commits

    def prefetch_commits(repo, commit_hashes):
        size = 1000
        chunks = [
            commit_hashes[i : i + size] for i in range(0, len(commit_hashes), size)
        ]
        n = len(chunks)
        for i, chunk in enumerate(chunks, start=1):
            ui.write(f"{int(time.time())}: {i}/{n}\n")
            try:
                repo.pull(headnames=chunk)
            except error.RepoLookupError as e:
                print(e)

    ui.write(f"generating merge data from file {filepath} ...\n")
    merge_commits = get_merge_commits_from_file(filepath)

    commits = list(dict.fromkeys([c for group in merge_commits for c in group]))
    ui.write(f"prefetching {len(commits)} commits ...\n")
    prefetch_commits(repo, commits)
    ui.write(f"prefetching done\n")

    ctxs = []
    nonlinear_merge = 0
    lookuperr = 0
    n = len(merge_commits)
    for i, (p1, p2, merge_commit) in enumerate(merge_commits, start=1):
        try:
            p2ctx = repo[p2]
            parents = repo.dageval(lambda: parentnames(p2ctx.node()))
            if len(parents) != 1:
                nonlinear_merge += 1
                continue
            basectx = repo[parents[0]]
            p1ctx = repo[p1]
            mergectx = repo[merge_commit]
            ctxs.append((p1ctx, p2ctx, basectx, mergectx))
        except error.RepoLookupError:
            lookuperr += 1
        if i % 100 == 0:
            ui.write(f"{int(time.time())}: {i}/{n} lookuperr={lookuperr}\n")

    ui.write(f"len(merge_ctxs)={len(ctxs)}, nonlinear_merge={nonlinear_merge}\n")
    return ctxs


def merge_file(
    repo, dstctx, srcctx, basectx, mergectx, filepath, m3merger, bench_stats
):
    srctext = srcctx[filepath].data()
    dsttext = dstctx[filepath].data()
    basetext = basectx[filepath].data()

    if srctext == dsttext or srctext == basetext or dsttext == basetext:
        return

    bench_stats.changed_files += 1

    m3 = m3merger(basetext, dsttext, srctext)
    mergedlines, conflictscount = render_minimized(m3)
    mergedtext = b"".join(mergedlines)

    if conflictscount:
        bench_stats.unresolved_files += 1
    else:
        expectedtext = mergectx[filepath].data()
        if remove_white_space(mergedtext) != remove_white_space(expectedtext):
            bench_stats.unmatched_files += 1
            mergedtext_baseline = b""

            if m3merger != Merge3Text:
                m3_baseline = Merge3Text(basetext, dsttext, srctext)
                mergedtext_baseline = b"".join(render_minimized(m3_baseline)[0])

            if mergedtext != mergedtext_baseline:
                repo.ui.write(
                    f"\nUnmatched_file: {filepath} {dstctx} {srcctx} {basectx} {mergectx}\n"
                )
                difftext = unidiff(mergedtext, expectedtext, filepath).decode("utf8")
                repo.ui.write(f"{difftext}\n")


def unidiff(atext, btext, filepath="") -> bytes:
    """
    generate unified diff between two texts.

    >>> basetext = b"a\\nb\\nc\\n"
    >>> atext = b"a\\nd\\nc\\n"
    >>> print(unidiff(basetext, atext).decode("utf8")) # doctest: +NORMALIZE_WHITESPACE
    --- a/
    +++ b/
    @@ -1,3 +1,3 @@
     a
    -b
    +d
     c
    """
    headers, hunks = mdiff.unidiff(atext, "", btext, "", filepath, filepath)
    result = headers
    for hunk in hunks:
        result.append(b"".join(hunk[1]))
    return b"\n".join(result)


def render_mergediff2(m3, name_a, name_b):
    lines = []
    conflicts = False
    for what, group_lines in m3.merge_groups(automerge=True):
        if what == "conflict":
            base_lines, a_lines, b_lines = group_lines
            basetext = b"".join(base_lines)
            bblocks = list(
                mdiff.allblocks(
                    basetext,
                    b"".join(b_lines),
                    lines1=base_lines,
                    lines2=b_lines,
                )
            )
            ablocks = list(
                mdiff.allblocks(
                    basetext,
                    b"".join(a_lines),
                    lines1=base_lines,
                    lines2=b_lines,
                )
            )

            def difflines(blocks, lines1, lines2):
                for block, kind in blocks:
                    if kind == "=":
                        for line in lines1[block[0] : block[1]]:
                            yield b" " + line
                    else:
                        for line in lines1[block[0] : block[1]]:
                            yield b"-" + line
                        for line in lines2[block[2] : block[3]]:
                            yield b"+" + line

            lines.append(b"<<<<<<< %s\n" % name_a)
            lines.extend(difflines(ablocks, base_lines, a_lines))
            lines.append(b"=======\n")
            lines.extend(difflines(bblocks, base_lines, b_lines))
            lines.append(b">>>>>>> %s\n" % name_b)
            conflicts = True
        else:
            lines.extend(group_lines)
    return lines, conflicts


def readfile(path):
    with open(path, "rb") as f:
        return f.read()


def remove_white_space(text):
    return re.sub(WHITE_SPACE_PATTERN, b"", text)


if __name__ == "__main__":
    import doctest

    doctest.testmod()
