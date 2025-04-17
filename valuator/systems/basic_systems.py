from modules import basic_modules

def subsystem_example_dating_corps():
    match_group_analysis = basic_modules.run('match group')
    grindr_analysis = basic_modules.run('grindr')

    return (match_group_analysis, grindr_analysis)


def run():
    adsf = subsystem_example_dating_corps()
    return adsf