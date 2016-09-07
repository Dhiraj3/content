cmds = demisto.getAllSupportedCommands()
repos = [x for x in cmds.keys() if cmds[x] and len(cmds[x]) == 1 and cmds[x][0]['name'] == 'epo-command']
demisto.setContext('eporepos', repos)
if repos:
    mdText = '### Repositories:'
    for r in repos:
        mdText += '\n * ' + r
else:
    mdText = 'No repositories found.'
demisto.results({"Type": entryTypes["note"], "ContentsFormat": formats["markdown"], "Contents": mdText})
