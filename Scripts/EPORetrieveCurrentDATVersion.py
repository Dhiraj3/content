res = []
repos = demisto.get(demisto.args(), 'repos')
if not repos:
    res.append({"Type": entryTypes["error"], "ContentsFormat": formats["text"], "Contents": "Received empty repository list!"})
else:
    repos = ','.join(repos) if isinstance(repos, list) else repos
    reqDat = demisto.get(demisto.args(), 'requireddatversion')
    # Find the VSCANDAT1000 Package
    dArgs = {"using": repos,
             "command": "repository.findPackages",
             "params": "searchText=VSCANDAT1000"
             }
    repoVersions = {}
    resCmdName = demisto.executeCommand('epo-command', dArgs)
    try:
        for entry in resCmdName:
            if isError(entry):
                res = resCmdName
                break
            else:
                repoName = entry['ModuleName']
                myData = demisto.get(entry, 'Contents.response')[0]['productDetectionProductVersion']
                repoVersions[repoName] = myData
    except Exception as ex:
        res.append({"Type": entryTypes["error"], "ContentsFormat": formats["text"],
                    "Contents": "Error occurred while parsing output from command. Exception info:\n" + str(ex) + "\n\nInvalid output:\n" + str(resCmdName)})

    demisto.setContext('repoversions', repoVersions)
    tbl = [{'Repository': k, 'Version of DAT': repoVersions[k]} for k in repoVersions]
    res.append({"Type": entryTypes["note"], "ContentsFormat": formats["table"], "Contents": tbl})
demisto.results(res)
