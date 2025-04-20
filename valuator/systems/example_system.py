from modules import example_module

def subsystem_example_dating_corps():
    match_group_analysis = example_module.run('match group')
    grindr_analysis = example_module.run('grindr')

    return (match_group_analysis, grindr_analysis)


def run(_: str) -> str:
    a, b = subsystem_example_dating_corps()
    return a + '\n' + b


from utils import test_runner
if __name__ == '__main__':
    test_runner.run(run)