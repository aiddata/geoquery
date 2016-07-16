angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, datasets) {

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
    { text: 'All', value: '' }
  ];

  $scope.dataFilters = { type: 'release', title: '' };

  $scope.selectDataset = function(dataset) {
    $scope.datasets.selected = dataset.name;
    $rootScope.$broadcast('dataset:selected', dataset);
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
