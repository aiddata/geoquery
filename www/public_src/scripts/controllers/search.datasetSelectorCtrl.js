angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, datasets, $state) {

  $scope.datasets = {
    filtered: [],
    options: [],
    selected: ''
  };

  $scope.fields = {
    options: ['date_added', 'date_updated', 'title', 'publishers', 'version'],
    selected: 'title',
    descending: false
  };

  $scope.dataTypes = [
    { text: 'AidData', value: 'release' },
    { text: 'External', value: 'raster' },
    { text: 'All', value: 'all' }
  ];

  $scope.search = function (item) {
    if ($scope.dataFilters.type !== 'all' &&
      item.type !== $scope.dataFilters.type) {
      return false;
    }

    return _.chain(item.extras.tags)
      .concat(item.title)
      .join(', ')
      .includes($scope.dataFilters.searchText)
      .value();
  };

  $scope.selectDataset = function(dataset) {
    var targetState = dataset.type === 'release' ? 'search.filters' :
        'search.options';

    $log.debug('Navigating to: ', targetState);

    $scope.datasets.selected = dataset.name;

    if (dataset.type === 'release') {
      console.log(dataset);
    }

    $state.go(targetState, { dataset: dataset.name });

  };

  $scope.$watch('datasets.filtered', function (newValue) {
    if (!newValue.length ||
      _.find($scope.datasets.filtered, { name: $scope.datasets.selected })
    ) {
      return;
    }
    $scope.selectDataset(_.head($scope.datasets.filtered));
  }, true);


  $scope.$on('$viewContentLoaded', function(event) {
    $scope.dataFilters = { searchText: '' };
    $scope.dataFilters.type = _.get(_.find(datasets, { name: $state.params.dataset }), 'type') || 'release';
    $scope.datasets.options = datasets;
  });
});
