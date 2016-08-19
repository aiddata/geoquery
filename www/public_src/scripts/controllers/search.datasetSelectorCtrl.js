angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, datasets, $state, info) {
  $scope.showSearchTools = false;
  $scope.featuredTags = [];
  $scope.datasets = {
    filtered: [],
    options: [],
    selected: ''
  };

  $scope.fields = {
    options: [{ display: 'Date Updated', value: 'date_updated'}, { display: 'Name', value: 'title'}],
    selected: '',
    descending: true
  };


  $scope.search = function (item) {
    if ($scope.dataFilters.tag !== 'all' &&
      item.extras.tags.indexOf($scope.dataFilters.tag) < 0 ) {
      return false;
    }

    return _.chain(item.extras.tags)
      .concat(item.title)
      .join(', ')
      .toLower()
      .includes(_.toLower($scope.dataFilters.searchText))
      .value();
  };

  $scope.selectDataset = function(dataset) {
    console.log(dataset);
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
    if ($state.params.dataset) {
      $scope.datasets.selected = $state.params.dataset;
    }
    $scope.dataFilters = { searchText: '', tag: 'all' };
    $scope.featuredTags = info.data_categories;

    var d = _.orderBy(datasets, 'type').reverse();      // Position AidData Datasets at the Top of Array
    $scope.datasets.options = d;
  });

});
