angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $stateParams, $state, $q, $log, ajaxFactory) {

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
    $stateParams.datatype = dataset.type;
    $state.go('search', $stateParams, { reload: false, notify: false })
      .then(function() {
        $rootScope.$broadcast('dataset:selected', dataset);
      });
  };

  $scope.$watch(function() {
    return $scope.datasets.filtered.length;
  }, function (newValue) {
    if (!newValue ||
      _.find($scope.datasets.filtered, { name: $scope.datasets.selected })) {
      return;
    }
    $scope.selectDataset(_.head($scope.datasets.filtered));
  }, true);

  function init () {
    ajaxFactory.datasets($stateParams.boundary)
      .then(function(results) {
        $scope.datasets.options = results.data;
      }, function(err) {
        $log.error(err);
      });
  }

  init();
});
