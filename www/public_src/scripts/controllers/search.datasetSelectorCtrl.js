angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, datasets, $state) {
  $scope.showSearchTools = false;

  $scope.datasets = {
    filtered: [],
    options: [],
    selected: ''
  };

  $scope.fields = {
    options: ['date_added', 'date_updated', 'title', 'publishers', 'version'],
    selected: 'type',     // Sort By type by default -- Positioning AidData at the top
    descending: true
  };

  $scope.dataTypes = [
    { text: 'All', value: 'all' },
    { text: 'AidData', value: 'release' },
    { text: 'External', value: 'raster' }
  ];

  $scope.selectedTabIndex = 1;


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

    $state.go(targetState, { dataset: dataset.name });

  };

  $scope.$watch('datasets.filtered', function (newValue) {
    if (newValue.length === 0 || _.find($scope.datasets.filtered, { name: $scope.datasets.selected }) ) {
      return;
    }
    $scope.selectDataset(_.head($scope.datasets.filtered));
  }, true);


  $scope.$on('$viewContentLoaded', function(event) {
    $scope.dataFilters = { searchText: '' };
    $scope.dataFilters.type = _.get(_.find(datasets, { name: $state.params.dataset }), 'type') || 'all';
    $scope.selectedTabIndex = _.findIndex($scope.dataTypes, { value: $scope.dataFilters.type }) + 1;

    var d = _.orderBy(datasets, 'type').reverse();      // Position AidData Datasets at the Top of Array
    $scope.datasets.options = d;
  });

  $scope.toggleToolBox = function() {
    $scope.showSearchTools = !$scope.showSearchTools;
  };
});
