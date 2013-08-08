#!/usr/bin/python

# coding=utf-8

import subprocess
import os
import re
import string
from itertools import ifilterfalse, imap, ifilter, islice, takewhile
from collections import namedtuple

AUTHOR = 'vladimir.vitvitskiy'

# ============== helper functions

def take(start, stop, iterable):
    return list(islice(iterable, start, stop))


def nth(n, seq):
    if seq and n > 0:
        v = take(n - 1, n, seq)
        if v:
            return v[0]


def first(seq):
    return nth(1, seq)


def second(seq):
    return nth(2, seq)


# ============== shell functions

def shell(cmd):
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout, p.stderr


def strict_shell(cmd):
    code, out, err_ = shell(cmd)
    if code:
        err_msg = '\n'.join(err_.readlines())
        out_msg = '\n'.join(out.readlines())
        raise Exception("Failed to execute '%s'.\n"
                        "Error code %s.\n"
                        "Output: %s\n"
                        "Error: %s\n" % (cmd, code, out_msg, err_msg))
    return out


# ============== git functions
Author = namedtuple("Author", ('name', 'email'))
Commit = namedtuple("Commit", ('id_', 'author', 'message', 'files'))

def git(cmd, verbose=True):
    '@types: str -> list[str]'
    if verbose:
        print cmd
    return strict_shell(cmd).readlines()


def git_str(cmd, verbose=False):
    return '\n'.join(git(cmd, verbose=verbose))


def git_get_details(id_):

    CHANGED_FILE_RE = re.compile(r'(.*?)\s+\|\s+\d+\s+[\+\-]*')

    def parse_author(v):
        m = re.match(r'\s*(.*?)\s*<(.*?)>\s*', v.strip())
        return m and Author(*m.groups())

    def parse_changed_file(line):
        m = CHANGED_FILE_RE.match(line)
        return m and m.group(1)

    def is_not_changed_file_section(line):
        return not bool(CHANGED_FILE_RE.match(line))

    def parse_changed_files(lines):
        files = imap(parse_changed_file, lines)
        files = imap(string.strip, takewhile(bool, files))
        return '\n'.join(files)

    def parse_msg(lines):
        return '\n'.join(takewhile(is_not_changed_file_section, lines))

    def parse(lines):
        lines = filter(bool, lines)
        _, cid = lines[0].split(' ')
        _, author_str = lines[1].split(':', 1)
        author = parse_author(author_str)
        message = parse_msg(islice(lines, 2, len(lines)))
        # skip the latest line - summary of changes
        reversed_lines = lines[-2::-1]
        files = parse_changed_files(reversed_lines)
        return cid, author, message, files

    lines = git('git show --stat %s' % id_, verbose=False)
    _, author, message, changed_files = parse(lines)
    return Commit(id_, author, message, changed_files)


def git_cherry_pick(id_, with_commit=True):
    try:
        with_commit = not with_commit and '-n' or ''
        output = git_str("git cherry-pick "
                         "-x " # put in the message body about the cherry-picked commit
                         "%s %s" % (with_commit, id_))
        return True
    except ValueError, v:
        print str(v)
    return False


def git_partial_cherry_pick(id_):
    return git_cherry_pick(id_, with_commit=False)


def is_candidate(id_):
    details = git_get_details(id_)
    return (details.author
            and details.author.email.find(AUTHOR) > -1)


def git_get_all_missed_commits(in_=None, from_="HEAD"):
    lines = git('git cherry %s %s' % (in_, from_))

    def parse_commit_info(line):
        tokens = line.split(' ')
        if tokens and len(tokens) == 2:
            sign, id_ = tokens
            is_present = sign == '-'
            return is_present, id_.strip()
        return None

    commits = imap(parse_commit_info, lines)
    commits = ifilter(bool, commits)
    return imap(second, ifilterfalse(first, commits))


def get_get_cherry_picked_ids(branch):

    CP_RE = re.compile(r'.*?\s+(\w+?)\)$')
    def parse_cherry_picked_ids(line):
        m = CP_RE.match(line)
        return m and m.group(1)

    lines = git('git log --grep="cherry picked from commit"'
                '| ack "^\s+\(cherry picked from commit"', verbose=True)
    ids = imap(parse_cherry_picked_ids, lines)
    return set(ifilter(bool, ids))


def git_commit_partial_cherry_pick():
    git("git ci -c %s" % PARTIAL_CP)


def git_is_clean_status():
    out = git_str('git status -v', verbose=False)
    return out.find('working directory clean') > -1


def git_show_commit_info(id_):
    lines = ifilter(len, imap(string.strip, git('git show --name-only %s' % id_)))
    print '\n'.join(lines)


SKIP = 's'
IGNORE = 'i'
CHERRY_PICK = 'c'
PARTIAL_CHERRY_PICK = 'p'
COMMAND_TO_DESCR = {
    SKIP: '(s)kip',
    IGNORE: '(i)gnore',
    CHERRY_PICK: '(c)herry-pick',
    PARTIAL_CHERRY_PICK: '(p)artial cherry-pick'
}


def _ask_bool(msg, true_answer, false_answer):
    msg = "%s (%s/%s): " % (msg, true_answer, false_answer)
    return raw_input(msg) == true_answer


def ask_to_resolve_status():
    print 'Seems like your working directory is not clean'
    raw_input("Type ENTER when ready to continue...")


def ask_what_to_do_with_commmit():
    commands = '|'.join(COMMAND_TO_DESCR.itervalues())
    prompt = "Command: %s: " % commands
    print ''
    choice = raw_input(prompt)
    while not choice in COMMAND_TO_DESCR:
        choice = raw_input(prompt)
    return choice


def parse_parameters(argv):
    import getopt
    try:
       opts, args = getopt.getopt(argv,"h:",[])
       if not (args and len(args) == 2):
           raise ValueError()
       upstream, head = args
    except (getopt.GetoptError, ValueError):
       print 'main.py <upstream> <head>'
       sys.exit(2)
    return upstream, head


def _compose_ignore_file_name(upstream, head):
    return '/tmp/%s_%s.ignored' % (upstream, head)


def read_commit_ids_to_ignore(upstream, head):
    path_ = _compose_ignore_file_name(upstream, head)
    if os.path.exists(path_):
        with open(path_, "r+") as f:
            return set(imap(string.strip, f.readlines()))
    return set()


def ignore_commit(upstream, head, id_):
    with open(_compose_ignore_file_name(upstream, head), "a+") as f:
        print >>f, id_


def main(upstream, head):
    git_dir = get_git_dir()
    ignored_ids = read_commit_ids_to_ignore(upstream, head)
    cherry_picked_ids = get_get_cherry_picked_ids(upstream)

    commit_ids = git_get_all_missed_commits(in_="cp12_sap", from_="master")
    commit_ids = ifilter(is_candidate, commit_ids)
    commit_ids = (id_ for id_ in commit_ids
                  if (id_ not in ignored_ids
                      and id_ not in cherry_picked_ids))

    for id_ in commit_ids:
        print '=' * 79
        print 'save state for: ', id_
        save_state_about_commit_to_review(id_)
        while not git_is_clean_status():
            ask_to_resolve_status()
        git_show_commit_info(id_)
        choice = ask_what_to_do_with_commmit()
        if choice == SKIP:
            print 'Skip ', id_
            continue
        elif choice == IGNORE:
            ignore_commit(upstream, head, id_)
            ignored_ids.add(id_)
        elif choice == CHERRY_PICK:
            git_cherry_pick(id_)
        elif choice == PARTIAL_CHERRY_PICK:
            git_partial_cherry_pick(id_)
            put_in_cherry_pick_head(git_dir, id_)
            # while not git_is_clean_status():
            #     if _ask_bool("Commit resolved partial cherry pick ?", 'y', 'n'):
            #         git_commit_partial_cherry_pick()
            #         remove_partial_cherry_pick_head(git_dir)

PARTIAL_CP = "CHERRY_PICK_HEAD"

def _compose_partial_cp_head(git_dir):
    return "%s/%s" % (git_dir, PARTIAL_CP)

def remove_partial_cherry_pick_head(git_dir):
    import os
    os.remove(_compose_partial_cp_head(git_dir))

def put_in_cherry_pick_head(git_dir, id_):
    with open(_compose_partial_cp_head(git_dir), "w+") as f:
        print >>f, id_

def save_state_about_commit_to_review(id_):
    with open("/tmp/commmit_to_review", "w+") as f:
        print >>f, id_,

def get_git_dir():
    #MERGE_HEAD
    from os import path, getcwd
    dir = path.abspath(getcwd())
    git_dir = path.exists("%s/.git/" % dir)

    while dir and not git_dir:
        dir = path.dirname(dir)
        git_dir = path.exists("%s/.git/" % dir)

    if not git_dir:
        raise ValueError("No git repository found")

    return "%s/.git/" % dir


if __name__ == '__main__':
    import sys
    try:
        main(*parse_parameters(sys.argv[1:]))
    except KeyboardInterrupt, e:
        print ''
        print 'interrupted'
