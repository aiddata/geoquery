angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, datasets, $state, $stateParams, $timeout, queryFactory) {

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

  $scope.dataFilters = { searchText: '' };
  $scope.dataFilters.type = _.get(_.find(datasets, { name: $state.params.dataset }), 'type');


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
    $scope.datasets.selected = dataset.name;
    //
    // queryFactory.setDataset(data.name);
    var targetState = dataset.type === 'release' ? 'search.filters' : 'search.options';
    $state.go(targetState, { dataset: dataset.name })
      .then(function() {
        $timeout(function() {
          $rootScope.$broadcast('dataset:selected', dataset);
        });
      });
  };

  $scope.$watch('datasets.filtered', function (newValue) {
    if (!newValue.length ||
      _.find($scope.datasets.filtered, { name: $scope.datasets.selected })) {
      return;
    }
    $scope.selectDataset(_.head($scope.datasets.filtered));
  }, true);

  function init () {
    $scope.datasets.options = datasets;
  }
  init();
});
