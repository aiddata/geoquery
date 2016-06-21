angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $stateParams, $q, ajaxFactory) {
  $scope.datasets = {
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

  $scope.dataFilters = { type: '', title: '' };

  ajaxFactory.datasets($stateParams.geomId)
    .then(function(results) {
      $scope.datasets.options = results.data;
      $scope.selectDataset($scope.datasets.options[0]);
    });

  $scope.selectDataset = function(dataset) {
    $scope.datasets.selected = dataset.name;
    $rootScope.$broadcast('dataset:selected', _.pick(dataset, ['name', 'title']));
  };

  $scope.filterType = function (type) {
    $scope.dataFilters.type = type.value;
  };
});
