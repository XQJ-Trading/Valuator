from valuator.modules import example_module

def subsystem_example_dating_corps():
    match_group_analysis = example_module.run('match group')
    grindr_analysis = example_module.run('grindr')

    return (match_group_analysis, grindr_analysis)


def run():
    adsf = subsystem_example_dating_corps()
    return adsf